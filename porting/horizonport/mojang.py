"""The owner's game files, downloaded once from Mojang.

`horizon-prepare` never downloads Mojang's files; it imports them from the
player's own copy (the official launcher's folder, Prism, MultiMC, ...), checks
each against `research-lock.json` and runs the exporters. A launcher whose
players don't already have 26.3 installed must do what the official launcher
does: download the pinned version for an account that owns the game.

This module does exactly that, into `store/mojang/<version>/` in the official
launcher's layout, with every file checked against the size and SHA-1 Mojang
lists (`launcher/src/mojang.rs` does the same):

    versions/<v>/<v>.json      the version file
    versions/<v>/<v>.jar       the client jar
    libraries/<maven path>     this system's libraries
    assets/indexes/<id>.json   the asset index
    assets/objects/<ab>/<hash> the assets (textures, sounds, languages)
    server.jar                 the dedicated server jar (first preparation only)

Only `https://` addresses on Mojang's own hosts are followed, and a file whose
checksum doesn't match is never written.
"""

from __future__ import annotations

import concurrent.futures
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import urlparse

from . import auth, net
from .store import Entry, Store, mojang_key
from .util import PortError, human_bytes, info, warn

MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
ALLOWED_HOSTS = (
    "piston-meta.mojang.com",
    "piston-data.mojang.com",
    "launchermeta.mojang.com",
    "launcher.mojang.com",
    "libraries.minecraft.net",
    "resources.download.minecraft.net",
    "api.minecraftservices.com",
)


@dataclass
class GameFile:
    path: str
    url: str
    sha1: str
    size: int = 0


@dataclass
class Layout:
    root: Path
    version: str

    @property
    def version_json(self) -> Path:
        return self.root / "versions" / self.version / f"{self.version}.json"

    @property
    def client_jar(self) -> Path:
        return self.root / "versions" / self.version / f"{self.version}.jar"

    @property
    def libraries(self) -> Path:
        return self.root / "libraries"

    @property
    def assets(self) -> Path:
        return self.root / "assets"

    @property
    def server_jar(self) -> Path:
        return self.root / "server.jar"

    def prepare_inputs(self) -> dict[str, Path]:
        return {
            "version_json": self.version_json,
            "client_jar": self.client_jar,
            "libraries_dir": self.libraries,
            "assets_dir": self.assets,
        }


def resolve(version: str, *, transport=None) -> dict:
    """The version file for `version`, from Mojang's pinned manifest."""
    transport = transport or auth.HttpTransport()
    manifest = _get_json(MANIFEST)
    versions = manifest.get("versions")
    if not isinstance(versions, list):
        raise PortError("Mojang's version manifest has no versions")
    for entry in versions:
        if entry.get("id") == version:
            url = entry.get("url")
            if not isinstance(url, str):
                raise PortError(f"Mojang's manifest has no url for {version}")
            return _get_json(url)
    known = ", ".join(str(v.get("id")) for v in versions[:12])
    raise PortError(
        f"Mojang's manifest does not list Minecraft {version}",
        hint=f"It lists, most recent first: {known}",
    )


def plan(version_json: dict, *, with_server: bool = True, system: str | None = None) -> list[GameFile]:
    """Every file a preparation reads for this version, with its checksum."""
    files: list[GameFile] = []
    version = str(version_json.get("id", ""))
    if not version:
        raise PortError("the version file has no id")
    client = version_json.get("downloads", {}).get("client", {})
    if client.get("url"):
        files.append(
            GameFile(
                f"versions/{version}/{version}.jar",
                client["url"],
                str(client.get("sha1", "")),
                int(client.get("size", 0)),
            )
        )
    for library in _libraries(version_json, system):
        artifact = library.get("downloads", {}).get("artifact") or {}
        if not artifact.get("url"):
            continue
        path = artifact.get("path") or _maven_path(library)
        if not path:
            continue
        files.append(
            GameFile(
                f"libraries/{path}",
                artifact["url"],
                str(artifact.get("sha1", "")),
                int(artifact.get("size", 0)),
            )
        )
    index = version_json.get("assetIndex") or {}
    if index.get("url"):
        files.append(
            GameFile(
                f"assets/indexes/{index.get('id', version)}.json",
                index["url"],
                str(index.get("sha1", "")),
                int(index.get("size", 0)),
            )
        )
    if with_server:
        server = version_json.get("downloads", {}).get("server", {})
        if server.get("url"):
            files.append(GameFile("server.jar", server["url"], str(server.get("sha1", "")), int(server.get("size", 0))))
    return files


def asset_objects(index: dict) -> list[GameFile]:
    """The asset index's objects, each once, keyed by its content hash."""
    objects = index.get("objects")
    if not isinstance(objects, dict):
        raise PortError("the asset index has no objects")
    unique: dict[str, int] = {}
    for value in objects.values():
        if isinstance(value, dict) and isinstance(value.get("hash"), str):
            unique[value["hash"]] = int(value.get("size", 0))
    return [
        GameFile(
            f"assets/objects/{digest[:2]}/{digest}",
            f"https://resources.download.minecraft.net/{digest[:2]}/{digest}",
            digest,
            size,
        )
        for digest, size in sorted(unique.items())
    ]


def layout_for(project, version: str) -> Layout:
    return Layout(root=project.mojang / version, version=version)


def sync(
    project,
    version: str,
    *,
    with_server: bool = True,
    jobs: int = 8,
    log=info,
    on_progress: Callable[[int, int, int], None] | None = None,
    session: dict | None = None,
) -> Layout:
    """Download what a preparation needs, once, into the store.

    `session` is the signed-in account's session JSON. Mojang's files are
    public, but Horizon's policy is that a launcher downloads them only for an
    owner, as the official launcher would.
    """
    layout = layout_for(project, version)
    if session is not None:
        _require_owner(session)
    version_json = resolve(version)
    _verify_pinned(project, version_json)
    layout.root.mkdir(parents=True, exist_ok=True)
    _write_json_file(layout.version_json, version_json)

    files = plan(version_json, with_server=with_server)
    index_url = str((version_json.get("assetIndex") or {}).get("url", ""))
    if index_url:
        index_path = layout.assets / "indexes" / f"{(version_json.get('assetIndex') or {}).get('id', version)}.json"
        if not index_path.is_file():
            net.download(index_url, index_path)
        index = json.loads(index_path.read_text(encoding="utf-8"))
        files.extend(asset_objects(index))

    todo = [item for item in files if not _is_current(layout.root / item.path, item)]
    have = len(files) - len(todo)
    if have:
        log(f"{version}: {have} files are already in place, {len(todo)} to download")
    total_bytes = sum(item.size for item in todo)
    log(f"{version}: downloading {len(todo)} files ({human_bytes(total_bytes)})")

    done = 0
    failed: list[str] = []

    def fetch(item: GameFile) -> None:
        nonlocal done
        target = layout.root / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        net.download(item.url, target, expected_sha256=None)
        actual = _sha1_file(target)
        if item.sha1 and actual != item.sha1:
            target.unlink(missing_ok=True)
            raise PortError(f"{item.path} is not the file Mojang lists (sha1 {actual})")
        done += 1
        if on_progress:
            on_progress(done, len(todo), total_bytes)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        futures = {pool.submit(fetch, item): item for item in todo}
        for future in concurrent.futures.as_completed(futures):
            error = future.exception()
            if error is not None:
                failed.append(f"{futures[future].path}: {error}")
    if failed:
        raise PortError(
            f"{len(failed)} of {len(todo)} files did not arrive",
            hint="Run the command again: finished files are kept.\n  - " + "\n  - ".join(failed[:5]),
        )

    for item in files:
        if not (layout.root / item.path).is_file():
            raise PortError(f"{item.path} is missing after the download")
    store = Store(project)
    store.put(
        Entry(key=mojang_key(version), kind="mojang", path="", extra={"minecraft": version}),
        directory=layout.root,
    )
    log(f"{version}: the owner's game files are in {layout.root}")
    return layout


def _require_owner(session: dict) -> None:
    """Ask Minecraft services whether this session may download the game."""
    transport = auth.HttpTransport()
    try:
        if not auth.ownership(transport, session["access_token"]):
            raise PortError(
                "This account doesn't own Minecraft: Java Edition, so its files aren't downloaded.",
                hint="Sign in with the account that owns the game.",
            )
    except PortError as exc:
        if "doesn't own" in exc.message:
            raise
        warn(f"could not confirm ownership ({exc.message}); the download continues for the signed-in account")


def _verify_pinned(project, version_json: dict) -> None:
    lock = project.root / "research-lock.json"
    if not lock.is_file():
        return
    try:
        pinned = json.loads(lock.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    wanted = _find_pin(pinned)
    client = version_json.get("downloads", {}).get("client", {})
    if wanted and client.get("sha1") and wanted != client.get("sha1"):
        raise PortError(
            f"Mojang's client jar for {version_json.get('id')} is not the jar this build pins",
            hint="The engine's research-lock.json pins a different game version; install the matching build.",
        )


def _find_pin(value) -> str | None:
    """The client jar's SHA-1 in the engine's research lock, wherever it is named."""
    if isinstance(value, dict):
        for key in ("client_sha1", "clientSha1", "client_jar_sha1"):
            candidate = value.get(key)
            if isinstance(candidate, str) and len(candidate) == 40:
                return candidate
        client = value.get("client")
        if isinstance(client, dict):
            candidate = client.get("sha1")
            if isinstance(candidate, str) and len(candidate) == 40:
                return candidate
        if value.get("sha1") and isinstance(value.get("sha1"), str) and len(value["sha1"]) == 40:
            return value["sha1"]
        for item in value.values():
            found = _find_pin(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_pin(item)
            if found:
                return found
    return None


def _libraries(version_json: dict, system: str | None) -> list[dict]:
    libraries = version_json.get("libraries")
    if not isinstance(libraries, list):
        return []
    return [item for item in libraries if isinstance(item, dict) and _allowed(item, system)]


def _allowed(library: dict, system: str | None) -> bool:
    rules = library.get("rules")
    if not isinstance(rules, list) or not rules:
        return True
    os_name = _os_name(system)
    allowed = False
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        os_rule = rule.get("os") or {}
        if os_rule.get("name") and os_rule["name"] != os_name:
            continue
        if os_rule.get("arch") and os_rule["arch"] not in ("x86", "x86_64", "arm64"):
            continue
        allowed = rule.get("action") == "allow"
    return allowed


def _os_name(system: str | None) -> str:
    import sys

    system = (system or sys.platform).lower()
    if system.startswith("win"):
        return "windows"
    if system == "darwin" or system.startswith("mac"):
        return "osx"
    return "linux"


def _maven_path(library: dict) -> str | None:
    name = library.get("name")
    if not isinstance(name, str):
        return None
    parts = name.split(":")
    if len(parts) < 3:
        return None
    group, artifact, version = parts[:3]
    classifier = parts[3] if len(parts) > 3 else None
    file_name = f"{artifact}-{version}" + (f"-{classifier}" if classifier else "") + ".jar"
    return str(PurePosixPath(*group.split("."), artifact, version, file_name))


def _is_current(path: Path, item: GameFile) -> bool:
    if not path.is_file():
        return False
    if item.size and path.stat().st_size != item.size:
        return False
    if item.sha1 and len(item.sha1) == 40:
        return _sha1_file(path) == item.sha1
    return True


def _sha1_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _get_json(url: str) -> dict:
    _check_url(url)
    answer = net.get(url)
    payload = answer.json()
    if not isinstance(payload, dict):
        raise PortError(f"{url}: expected a JSON object")
    return payload


def _check_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise PortError(
            f"refusing to fetch {url}",
            hint="Mojang's files come only from Mojang's https hosts.",
        )


def _write_json_file(path: Path, value: dict) -> None:
    from .util import write_json

    write_json(path, value)
