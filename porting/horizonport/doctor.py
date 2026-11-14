"""`horizonport doctor`: is this machine able to build and run a port?

Every check says one of four things:

    PASS  this is ready
    WARN  it works, but you will want to fix it (or a player feature suffers)
    FAIL  a port cannot work without it
    INFO  a fact worth putting in a bug report

The command exits 1 when anything FAILs, so CI can gate on it.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import sys
from pathlib import Path

from . import prepare, sign
from .config import PortProject
from .store import Store
from .util import PortError, human_bytes, platform_archive, run, table, which

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"


def collect(project: PortProject | None, *, full: bool = False) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    rows.append((INFO, "platform", f"{platform.system()} {platform.release()} ({platform.machine()})"))
    rows.append((INFO, "python", f"{platform.python_version()} at {sys.executable}"))
    archive, _ = platform_archive()
    rows.append((INFO, "horizon build for this machine", archive))

    rows.append(_python())
    rows.append(_git())
    rows.append(_java())
    rows.append(_rust())
    rows.append(_node())
    rows.append(_keys())
    if project is not None:
        rows.extend(_project(project, full=full))
        rows.append(_disk(project))
        rows.append(_writable(project))
        rows.append(_minecraft(project))
    return rows


def render(rows: list[tuple[str, str, str]]) -> int:
    table(rows, headers=("status", "what", "detail"))
    failures = sum(1 for row in rows if row[0] == FAIL)
    warnings = sum(1 for row in rows if row[0] == WARN)
    if failures:
        print(f"\n{failures} check(s) failed, {warnings} warning(s). Fix the failures before porting.")
        return 1
    if warnings:
        print(f"\nEverything required is present; {warnings} warning(s) above are worth reading.")
    else:
        print("\nEverything this port needs is present.")
    return 0


def _python() -> tuple[str, str, str]:
    version = sys.version_info
    if version < (3, 11):
        return (FAIL, "python >= 3.11", f"this is {platform.python_version()}; tomllib and task groups need 3.11")
    return (PASS, "python >= 3.11", platform.python_version())


def _git() -> tuple[str, str, str]:
    git = which("git")
    if not git:
        return (WARN, "git", "not on PATH: you cannot clone the engine, but an installed build still works")
    result = run([git, "--version"])
    return (PASS, "git", (result.stdout or "").strip() or git)


def _java() -> tuple[str, str, str]:
    candidates: list[Path] = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]) / "bin" / "java")
    on_path = which("java")
    if on_path:
        candidates.append(Path(on_path))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        result = run([str(candidate), "-version"])
        text = (result.stderr or "") + (result.stdout or "")
        found = re.search(r'version "(\d+)', text)
        major = int(found.group(1)) if found else 0
        if major >= 25:
            return (PASS, "java", f"major {major} at {candidate}")
        return (
            WARN,
            "java",
            f"major {major} at {candidate}; preparation needs 25 (pass --java-home, or let the launcher install one)",
        )
    return (
        WARN,
        "java",
        "no java on PATH; horizon-prepare needs Java 25, or a --java-home that has it",
    )


def _rust() -> tuple[str, str, str]:
    rustc = which("rustc")
    if not rustc:
        return (
            WARN,
            "rust (optional)",
            "no rustc: only needed to build the engine from source or native mods; a release build does not",
        )
    result = run([rustc, "--version"])
    return (PASS, "rust (optional)", (result.stdout or "").strip())


def _node() -> tuple[str, str, str]:
    node = which("node")
    if not node:
        return (INFO, "node (optional)", "not on PATH; only the Node adapter template needs it")
    result = run([node, "--version"])
    return (PASS, "node (optional)", (result.stdout or "").strip())


def _keys() -> tuple[str, str, str]:
    try:
        keys = sign.default_keys()
    except PortError as exc:
        return (FAIL, "release keys", exc.message)
    if not keys:
        return (FAIL, "release keys", "no key: no downloaded build could be verified")
    return (PASS, "release keys", f"{len(keys)} Ed25519 key(s)")


def _project(project: PortProject, *, full: bool) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    problems = project.problems()
    if problems:
        rows.append((FAIL, "port.config.json", problems[0] + (f" (+{len(problems) - 1} more)" if len(problems) > 1 else "")))
    else:
        rows.append((PASS, "port.config.json", f"{project.name}, Minecraft {project.minecraft}"))
    rows.append(
        (
            PASS if project.data.is_dir() else WARN,
            "data folder",
            str(project.data),
        )
    )
    try:
        store = Store(project)
    except PortError as exc:
        rows.append((FAIL, "store", exc.message))
        return rows
    builds = store.builds()
    prepared = store.prepared()
    rows.append(
        (
            PASS if builds else WARN,
            "builds installed",
            ", ".join(entry.key.split(":", 1)[1] for entry in builds) or "none: run `horizonport fetch`",
        )
    )
    rows.append(
        (
            PASS if prepared else WARN,
            "prepared resources",
            f"{len(prepared)} tree(s), {human_bytes(sum(entry.bytes for entry in prepared))}" if prepared else "none: run `horizonport prepare`",
        )
    )
    if full:
        for entry in builds + prepared:
            good, detail = store.verify(entry, full=True)
            rows.append((PASS if good else FAIL, entry.key, detail))
    adapter = project.adapter_entry
    if adapter is not None:
        rows.append((PASS if adapter.exists() else WARN, "adapter", str(adapter)))
    if project.client_id:
        rows.append((PASS, "microsoft client id", "configured (auth.clientId)"))
    else:
        rows.append((WARN, "microsoft client id", "not set: sign-in cannot work until you register an Azure app"))
    return rows


def _disk(project: PortProject) -> tuple[str, str, str]:
    path = project.data
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return (INFO, "disk", "could not measure free space")
    free = usage.free
    # A prepared tree is several GB with sounds; two builds plus one tree is the honest floor.
    if free < 6 * 1024**3:
        return (WARN, "disk", f"{human_bytes(free)} free at {path}; a build plus prepared resources needs ~6 GiB")
    return (PASS, "disk", f"{human_bytes(free)} free at {path}")


def _writable(project: PortProject) -> tuple[str, str, str]:
    try:
        project.data.mkdir(parents=True, exist_ok=True)
        probe = project.data / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return (FAIL, "data folder is writable", str(exc))
    return (PASS, "data folder is writable", str(project.data))


def _minecraft(project: PortProject) -> tuple[str, str, str]:
    found = prepare.known_minecraft_dirs()
    mojang = project.mojang
    have = mojang.is_dir() and any(mojang.iterdir())
    if have:
        return (PASS, "game files", f"downloaded once into {mojang}")
    if found:
        return (PASS, "game files", f"found a Minecraft install at {found[0]} (or download once with --download)")
    return (
        WARN,
        "game files",
        "no Minecraft install found; either play 26.3 once in the official launcher, or prepare --download for an owner",
    )
