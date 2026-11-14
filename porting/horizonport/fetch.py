"""Install a Horizon build: verify the signed checksums, unpack, check the layout.

A build is a release archive of the engine repository (`horizon-rust/horizon`
by default). It holds `horizon-client`, `horizon-prepare`, `research-lock.json`
and `exporters/`, and those files only work together, so a port keeps each
build in its own folder under `store/builds/<tag>/`.

The order here is the security contract:

1. download `SHA256SUMS` and `SHA256SUMS.sig`;
2. verify the Ed25519 signature over `horizon release <tag>\\n` + the sums;
3. download the archive and compare its SHA-256 with the signed sum;
4. unpack into `store/tmp/`, never into the destination;
5. check the programs exist, then move the folder into place.

A build that fails any step installs nothing.
"""

from __future__ import annotations

import json
import os
import platform
import stat
import sys
import tarfile
import zipfile
from pathlib import Path

from . import sign
from .net import download, get
from .store import Entry, Store, build_key
from .util import (
    PortError,
    human_bytes,
    info,
    platform_archive,
    program_name,
    remove_tree,
    run,
    sha256_file,
    warn,
)

PROGRAMS = ("horizon-client", "horizon-prepare")
MAX_ENTRIES = 200_000
MAX_UNPACKED = 32 * 1024**3


def release_url(repo: str, tag: str) -> str:
    if tag in ("latest",):
        return f"https://api.github.com/repos/{repo}/releases/latest"
    return f"https://api.github.com/repos/{repo}/releases/tags/{tag}"


def release_assets(repo: str, tag: str) -> dict[str, str]:
    """Asset name → download URL for one release."""
    answer = get(release_url(repo, tag))
    payload = answer.json()
    if not isinstance(payload, dict):
        raise PortError(f"{repo} {tag}: the release reply is not an object")
    assets = payload.get("assets")
    if not isinstance(assets, list) or not assets:
        raise PortError(
            f"{repo} {tag}: this release has no files",
            hint="Nightlies are deleted after seven days; pick a recent tag or a `nightly-<date>` one.",
        )
    found: dict[str, str] = {}
    for asset in assets:
        name = asset.get("name")
        url = asset.get("browser_download_url")
        if isinstance(name, str) and isinstance(url, str):
            found[name] = url
    return found


def install(
    project,
    tag: str,
    *,
    archive: Path | None = None,
    sums_file: Path | None = None,
    signature_file: Path | None = None,
    signature_for: str | None = None,
    allow_unsigned: bool = False,
    keys: list[bytes] | None = None,
    repo: str | None = None,
    log=info,
) -> Entry:
    """Make `tag` a verified build in the store, and return its entry."""
    store = Store(project)
    existing = store.find(build_key(tag))
    if existing and store.entry_path(existing).is_dir() and not archive:
        log(f"{tag} is already installed at {store.entry_path(existing)}")
        return existing

    if archive is None and sys.platform.startswith("linux") and platform.machine().lower() in ("aarch64", "arm64"):
        raise PortError(
            "Horizon publishes no Linux arm64 build",
            hint=(
                "Fetch on an x86_64 Linux machine (or under emulation) and pass the archive with "
                "--archive; Windows arm64 and macOS arm64 have native builds."
            ),
            code=1,
        )

    repo = repo or project.engine["repo"]
    target = project.builds / tag
    staging = store.staging(f"build-{_safe_name(tag)}")
    archive_sha = ""

    if archive is not None:
        archive = archive.expanduser().resolve()
        if not archive.is_file():
            raise PortError(f"{archive} does not exist")
        archive_sha = sha256_file(archive)
        if sums_file is not None:
            listed = _check_sums(
                sums_file,
                signature_file,
                tag if signature_for is None else signature_for,
                keys if keys is not None else _trusted_keys(project),
                allow_unsigned,
            )
            _require_match(listed, archive.name, archive_sha)
        elif not allow_unsigned:
            raise PortError(
                f"{archive.name} came without SHA256SUMS and a signature",
                hint=(
                    "Pass --sums and --signature from the release, or --allow-unsigned for a "
                    "build you compiled yourself."
                ),
            )
        else:
            warn(f"installing {archive.name} without a signature (unsigned build, your choice)")
        log(f"unpacking {archive.name} ({human_bytes(archive.stat().st_size)})")
        extract(archive, staging)
    else:
        log(f"asking {repo} for the {tag} release")
        assets = release_assets(repo, tag)
        names = set(assets)
        archive_name, _kind = platform_archive()
        archive_name = _pick(names, archive_name)
        sums_name = _pick(names, sign.SUMS)
        signature_name = sign.SIGNATURE
        if signature_for is not None and sign.SIGNATURE_V2 in names:
            signature_name = sign.SIGNATURE_V2
        signature_name = _pick(names, signature_name)
        sums_bytes = get(assets[sums_name]).body
        signature_text = get(assets[signature_name]).text
        listed = sign.verify_sums(
            signature_for if signature_for else tag,
            sums_bytes,
            signature_text,
            keys if keys is not None else _trusted_keys(project),
        )
        expected = sign.lookup(listed, archive_name)
        log(f"signature ok; {sums_name} lists {len(listed)} files")
        local = store.path / "downloads" / archive_name
        log(f"downloading {archive_name}")
        download(assets[archive_name], local, expected_sha256=expected)
        archive_sha = expected
        extract(local, staging)
        local.unlink(missing_ok=True)

    missing = missing_programs(staging)
    if missing:
        remove_tree(staging)
        raise PortError(
            f"{tag}: the archive is not a Horizon build; it lacks {', '.join(missing)}",
            hint="Pass the platform archive (horizon-windows-x64.zip, horizon-linux-x86_64.tar.gz, ...).",
        )
    _make_executable(staging)
    api = launch_api(staging)
    entry = Entry(
        key=build_key(tag),
        kind="build",
        path="",
        extra={
            "tag": tag,
            "archiveSha256": archive_sha,
            "launchApi": api,
        },
    )
    store.install_staging(staging, target)
    return store.put(entry, directory=target)


def extract(archive: Path, destination: Path) -> None:
    """Unpack a release archive safely: no absolute paths, no `..`, no links."""
    destination.mkdir(parents=True, exist_ok=True)
    name = archive.name.lower()
    if name.endswith(".zip"):
        _extract_zip(archive, destination)
    elif name.endswith((".tar.gz", ".tgz", ".tar")):
        _extract_tar(archive, destination)
    else:
        raise PortError(f"{archive.name}: unknown archive kind (zip, tar.gz, tgz or tar)")
    _flatten_single_folder(destination)


def _extract_zip(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) > MAX_ENTRIES:
            raise PortError(f"{archive.name}: {len(members)} entries is more than a build holds")
        total = 0
        for member in members:
            rel = _safe_member(member.filename, archive)
            mode = (member.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise PortError(f"{archive.name}: {member.filename} is a symlink; builds hold plain files")
            if member.is_dir():
                (destination / rel).mkdir(parents=True, exist_ok=True)
                continue
            total += member.file_size
            if total > MAX_UNPACKED:
                raise PortError(f"{archive.name}: unpacks to more than {human_bytes(MAX_UNPACKED)}")
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, open(target, "wb") as sink:
                while chunk := source.read(1024 * 1024):
                    sink.write(chunk)
            if mode & 0o111:
                target.chmod(target.stat().st_mode | 0o755)


def _extract_tar(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:*") as bundle:
        members = bundle.getmembers()
        if len(members) > MAX_ENTRIES:
            raise PortError(f"{archive.name}: {len(members)} entries is more than a build holds")
        total = 0
        for member in members:
            rel = _safe_member(member.name, archive)
            if member.isdir():
                (destination / rel).mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise PortError(
                    f"{archive.name}: {member.name} is a "
                    f"{'symlink' if member.issym() else 'hardlink' if member.islnk() else 'special file'}; "
                    "builds hold plain files"
                )
            total += member.size
            if total > MAX_UNPACKED:
                raise PortError(f"{archive.name}: unpacks to more than {human_bytes(MAX_UNPACKED)}")
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise PortError(f"{archive.name}: {member.name} has no contents")
            with source, open(target, "wb") as sink:
                while chunk := source.read(1024 * 1024):
                    sink.write(chunk)
            if member.mode & 0o111:
                target.chmod(target.stat().st_mode | 0o755)


def _safe_member(name: str, archive: Path) -> Path:
    cleaned = name.replace("\\", "/")
    parts = [part for part in cleaned.split("/") if part not in ("", ".")]
    if cleaned.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
        raise PortError(f"{archive.name}: {name!r} would write outside the build folder")
    if not parts:
        raise PortError(f"{archive.name}: {name!r} is an empty path")
    return Path(*parts)


def _flatten_single_folder(destination: Path) -> None:
    entries = list(destination.iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        return
    inner = entries[0]
    for child in inner.iterdir():
        child.rename(destination / child.name)
    inner.rmdir()


def missing_programs(directory: Path) -> list[str]:
    missing = [name for name in PROGRAMS if not _program(directory, name)]
    if not (directory / "research-lock.json").is_file():
        missing.append("research-lock.json")
    return missing


def _program(directory: Path, base: str) -> Path | None:
    for name in (base, program_name(base)):
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


def _make_executable(directory: Path) -> None:
    if os.name == "nt":
        return
    for base in PROGRAMS:
        path = _program(directory, base)
        if path:
            path.chmod(path.stat().st_mode | 0o755)


def launch_api(directory: Path) -> dict | None:
    """What this build says it supports, or None when it can't be asked."""
    client = _program(directory, "horizon-client")
    if client is None:
        return None
    try:
        result = run([str(client), "--launch-api"], cwd=directory, timeout=30)
    except PortError as exc:
        warn(f"could not ask {client.name} --launch-api ({exc.message})")
        return None
    if result.returncode != 0:
        warn(f"{client.name} --launch-api exited {result.returncode}: {result.stderr.strip()[:200]}")
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        warn(f"{client.name} --launch-api did not print JSON")
        return None
    return payload if isinstance(payload, dict) else None


def check_launch_api(directory: Path, default: dict | None = None) -> dict:
    api = default if default is not None else launch_api(directory)
    if not api:
        raise PortError(
            f"{directory} does not answer --launch-api",
            hint="The build is damaged or not a Horizon build; install it again.",
        )
    if not str(api.get("launch_api", "")).startswith("0.1"):
        warn(f"this build speaks Launch API {api.get('launch_api')!r}; HorizonPort is written for 0.1.x")
    return api


def _trusted_keys(project) -> list[bytes]:
    key_file = project.key_file()
    if key_file is not None:
        if not key_file.is_file():
            raise PortError(f"{key_file} does not exist")
        return sign.parse_keys(key_file.read_text(encoding="utf-8"))
    return sign.default_keys()


def _check_sums(
    sums_file: Path, signature_file: Path | None, tag: str, keys: list[bytes], allow_unsigned: bool
) -> list[tuple[str, str]]:
    sums = sums_file.read_bytes()
    if signature_file is None:
        if not allow_unsigned:
            raise PortError(
                f"{sums_file.name} came without its signature file",
                hint="Pass --signature SHA256SUMS.sig, or --allow-unsigned for a build you made.",
            )
        warn("trusting an unsigned checksum list (--allow-unsigned)")
        return sign.parse_sums(sums.decode("utf-8"))
    return sign.verify_sums(tag, sums, signature_file.read_text(encoding="utf-8"), keys)


def _require_match(listed: list[tuple[str, str]], name: str, actual: str) -> None:
    expected = sign.lookup(listed, name)
    if expected != actual:
        raise PortError(
            f"{name} does not match its signed checksum: got {actual}, expected {expected}",
            hint="Nothing was installed. The file may be damaged; download it again.",
        )


def _pick(names: set[str], wanted: str) -> str:
    if wanted in names:
        return wanted
    raise PortError(
        f"the release has no {wanted}",
        hint=f"It has: {', '.join(sorted(names)[:8])}{'...' if len(names) > 8 else ''}",
    )


def _safe_name(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-._" else "-" for c in value)
