"""Resources, prepared once per build and Minecraft version.

`horizon-prepare` imports the player's own game files, checks them against the
build's `research-lock.json`, runs Mojang's exporters on them and copies the
sounds. Its output is what `horizon-client --resources` reads, and it depends
on the build and the Minecraft version, **not** on the instance.

So HorizonPort prepares into `store/prepared/<key>/` and every instance points
at that one folder. Adding a second instance costs one `--check`: seconds, no
download. A new build gets a new key, because its layout (`output_version`) may
differ; the old tree stays until no instance uses it.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable

from . import fetch, mojang
from .store import Entry, Store, build_key, prepared_key
from .util import (
    PortError,
    human_bytes,
    info,
    platform_archive,
    program_name,
    remove_tree,
    run,
    step,
    warn,
)

MESSAGES = {
    0: "resources are complete",
    1: "preparation failed",
    2: "horizon-prepare refused the command line",
}


def preparer(build_dir: Path) -> Path:
    for name in ("horizon-prepare", program_name("horizon-prepare")):
        candidate = build_dir / name
        if candidate.is_file():
            return candidate
    raise PortError(
        f"{build_dir} has no horizon-prepare",
        hint="Install the build again: a release always ships the preparer beside the game.",
    )


def client(build_dir: Path) -> Path:
    for name in ("horizon-client", program_name("horizon-client")):
        candidate = build_dir / name
        if candidate.is_file():
            return candidate
    raise PortError(f"{build_dir} has no horizon-client")


def preparer_api(build_dir: Path) -> dict:
    result = run([str(preparer(build_dir)), "--launch-api"], cwd=build_dir, timeout=60)
    if result.returncode != 0:
        second = result.stderr.strip().splitlines()[:1]
        raise PortError(
            f"horizon-prepare --launch-api exited {result.returncode}"
            + (f": {second[0]}" if second else ""),
            hint="The build is damaged; install it again.",
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise PortError("horizon-prepare --launch-api did not print JSON") from None
    if not isinstance(payload, dict):
        raise PortError("horizon-prepare --launch-api printed something that is not an object")
    return payload


def check(build_dir: Path, output: Path) -> tuple[bool, str]:
    """Run the preparer's fast `--check` against a prepared folder."""
    result = run(
        [str(preparer(build_dir)), "--check", "--output", str(output)],
        cwd=build_dir,
        timeout=600,
    )
    text = (result.stdout or "").strip()
    if result.returncode == 0:
        return True, text
    return False, (text or (result.stderr or "").strip() or f"exit {result.returncode}")


def ensure(
    project,
    tag: str,
    *,
    minecraft_dir: Path | None = None,
    prism_dir: Path | None = None,
    inputs: dict[str, Path] | None = None,
    server_jar: Path | None = None,
    java_home: Path | None = None,
    download: bool = False,
    session: dict | None = None,
    force: bool = False,
    log=info,
    on_line: Callable[[str], None] | None = None,
    on_fraction: Callable[[float], None] | None = None,
) -> tuple[Entry, Path]:
    """Make sure this build has a complete prepared tree; return (entry, folder)."""
    store = Store(project)
    build_entry = store.find(build_key(tag))
    if build_entry is None:
        raise PortError(
            f"{tag} is not installed",
            hint=f"Run `horizonport fetch --tag {tag}` first.",
        )
    build_dir = store.entry_path(build_entry)
    if not build_dir.is_dir():
        raise PortError(f"{build_dir} is missing; install {tag} again")

    api = fetch.check_launch_api(build_dir, build_entry.extra.get("launchApi"))
    minecraft = str(api.get("minecraft") or project.minecraft)
    layout = api.get("output_version", api.get("schema"))
    key = prepared_key(tag, minecraft, layout)
    existing = store.find(key)

    if existing and not force:
        folder = store.entry_path(existing)
        if folder.is_dir():
            good, detail = check(build_dir, folder)
            if good:
                log(f"resources for {tag} are current: {folder}")
                return existing, folder
            log(f"resources for {tag} are not current ({_first_line(detail)}); preparing again")

    target = project.prepared / _folder_name(key)
    staging = store.staging(f"prepared-{_folder_name(key)}")

    sources: list[str] = []
    if download:
        wanted = str(api.get("minecraft") or project.minecraft)
        step(1, f"downloading Minecraft {wanted} from Mojang (once; every instance reuses it)")
        game = mojang.sync(
            project,
            wanted,
            log=log,
            session=session,
        )
        inputs = dict(inputs or {})
        inputs.update(game.prepare_inputs())
        server_jar = server_jar or game.server_jar
        sources.append("Mojang")
    if inputs:
        for name, path in sorted(inputs.items()):
            sources.append(f"{name}={path}")
    if minecraft_dir:
        sources.append(f"minecraft-dir={minecraft_dir}")
    if prism_dir:
        sources.append(f"prism-dir={prism_dir}")

    argv = [str(preparer(build_dir)), "--prepare", "--complete", "--progress", "json", "--output", str(staging)]
    if inputs:
        mapping = {
            "version_json": "--version-json",
            "client_jar": "--client-jar",
            "libraries_dir": "--libraries-dir",
            "assets_dir": "--assets-dir",
        }
        for name, flag in mapping.items():
            if name in inputs:
                argv += [flag, str(inputs[name])]
    if minecraft_dir:
        argv += ["--minecraft-dir", str(minecraft_dir)]
    if prism_dir:
        argv += ["--prism-dir", str(prism_dir)]
    if server_jar:
        argv += ["--server-jar", str(server_jar)]
    if java_home:
        argv += ["--java-home", str(java_home)]

    log(
        "preparing "
        + (", ".join(sources) if sources else "from your own Minecraft install")
        + " (this is the slow step: minutes, once)"
    )
    _run_preparer(argv, build_dir, log=log, on_line=on_line, on_fraction=on_fraction)

    good, detail = check(build_dir, staging)
    if not good:
        remove_tree(staging)
        raise PortError(
            f"the prepared folder is still incomplete: {_first_line(detail)}",
            hint="Run the command again; finished exporters are skipped.",
        )

    store.install_staging(staging, target)
    entry = Entry(
        key=key,
        kind="prepared",
        path="",
        extra={
            "build": tag,
            "minecraft": minecraft,
            "outputVersion": layout,
            "launchApi": api.get("launch_api"),
        },
    )
    entry = store.put(entry, directory=target)
    log(f"resources ready: {target} ({entry.files} files, {human_bytes(entry.bytes)})")
    return entry, target


def _run_preparer(
    argv: list[str],
    cwd: Path,
    *,
    log,
    on_line: Callable[[str], None] | None,
    on_fraction: Callable[[float], None] | None,
) -> None:
    env = dict(os.environ)
    env.setdefault("HORIZON_PREPARE_JOBS", str(max(1, min(8, os.cpu_count() or 1))))
    try:
        process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        raise PortError(f"{argv[0]} was not found") from None
    assert process.stdout is not None
    for raw in process.stdout:
        line = raw.strip()
        if not line:
            continue
        if on_line:
            on_line(line)
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            log(line)
            continue
        if "message" in event:
            log(str(event["message"]))
        elif "fraction" in event:
            if on_fraction:
                on_fraction(float(event["fraction"]))
        elif "error" in event:
            warn(str(event["error"]))
    stderr = process.stderr.read() if process.stderr else ""
    code = process.wait()
    if code != 0:
        detail = (stderr or "").strip().splitlines()[-1:] or [""]
        raise PortError(
            f"horizon-prepare: {MESSAGES.get(code, f'exit {code}')}"
            + (f": {detail[0]}" if detail[0] else ""),
            hint=(
                "Minecraft 26.3 must have been played once, the server jar must be the pinned one, "
                "and a Java of the pinned version must be installed. `horizonport doctor` checks the last two."
            ),
            code=1,
        )


def describe(project, tag: str) -> list[tuple[str, str, str]]:
    """What preparing this build will need, as a table for `horizonport prepare --plan`."""
    store = Store(project)
    entry = store.get(build_key(tag))
    build_dir = store.entry_path(entry)
    api = preparer_api(build_dir)
    rows = [
        ("build", tag, str(build_dir)),
        ("minecraft", str(api.get("minecraft", "?")), "the version file, client jar, libraries and assets"),
        ("java", f"major {api.get('java_major', '?')}", "JAVA_HOME, PATH, --java-home, or the official launcher's runtimes"),
        ("layout", str(api.get("output_version", api.get("schema", "?"))), "the prepared tree's identity"),
        ("server jar", "first preparation only", "downloads.server.url of that version's JSON"),
    ]
    return rows


def known_minecraft_dirs() -> list[Path]:
    """Folders other launchers keep the game in, for `--from-install` hints."""
    home = Path.home()
    candidates = [
        Path(os.environ.get("HORIZON_MINECRAFT_DIR", "")) if os.environ.get("HORIZON_MINECRAFT_DIR") else None,
        Path(os.environ.get("MINECRAFT_DIR", "")) if os.environ.get("MINECRAFT_DIR") else None,
        home / ".minecraft",
        home / "Library" / "Application Support" / "minecraft",
        Path(os.environ.get("APPDATA", "")) / ".minecraft" if os.environ.get("APPDATA") else None,
        home / ".local" / "share" / "PrismLauncher",
        home / "Library" / "Application Support" / "PrismLauncher",
        home / "AppData" / "Roaming" / "PrismLauncher",
        home / ".local" / "share" / "multimc",
    ]
    return [path for path in candidates if path and path.is_dir()]


def _folder_name(key: str) -> str:
    return "".join(c if c.isalnum() or c in "-._@" else "-" for c in key)


def _first_line(text: str) -> str:
    return (text.strip().splitlines() or ["no detail"])[0]
