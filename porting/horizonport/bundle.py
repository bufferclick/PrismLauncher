"""`horizonport bundle`: what a port ships, without a byte of Mojang's files.

The bundle is the hand-off between the port project and a release:

    horizonport-bundle.json   the pin: engine build, its signed archive hash,
                              the Minecraft version, the Launch API, digests
    adapter/                  the launcher-side code
    schemas/                  the JSON shapes
    AGENT-GUIDE.md            how to maintain it
    SHA256SUMS                a checksum per file, in sha256sum's format

It deliberately carries **no** prepared resources, no game files and no
sessions: those are made on the player's machine, for the player's account.
That keeps the bundle small, distributable and legal, and it is why a player's
first instance downloads once and every later one does not.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import instance as instance_mod
from .store import Store
from .util import human_bytes, now_utc, tree_files, write_json

SCHEMA = 1
KIT = Path(__file__).resolve().parents[1]


def build(project, *, out: Path | None = None) -> Path:
    store = Store(project)
    destination = (out or project.root / "dist" / "horizonport-bundle").resolve()
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    builds = []
    for entry in store.builds():
        api = entry.extra.get("launchApi") or {}
        builds.append(
            {
                "tag": entry.key.split(":", 1)[1],
                "archiveSha256": entry.extra.get("archiveSha256"),
                "files": entry.files,
                "bytes": entry.bytes,
                "launchApi": api.get("launch_api"),
                "minecraft": api.get("minecraft"),
            }
        )
    prepared = [
        {
            "key": entry.key,
            "digest": entry.digest,
            "files": entry.files,
            "bytes": entry.bytes,
            "build": entry.extra.get("build"),
            "minecraft": entry.extra.get("minecraft"),
        }
        for entry in store.prepared()
    ]
    files = {
        "horizonportBundle": SCHEMA,
        "name": project.name,
        "created": now_utc(),
        "engine": project.config["engine"],
        "minecraft": project.minecraft,
        "launchApi": "0.1.x",
        "policy": project.policy,
        "adapter": project.config["adapter"],
        "builds": builds,
        "prepared": prepared,
        "instances": instance_mod.summaries(project),
        "contents": "adapter, schemas, AGENT-GUIDE.md; no game files, no prepared resources",
    }
    write_json(destination / "horizonport-bundle.json", files)

    adapter = project.adapter_entry
    if adapter is not None and adapter.is_file():
        relative = adapter.relative_to(project.root)
        shutil.copytree(adapter.parent, destination / relative.parent, dirs_exist_ok=True)
    else:
        (destination / "adapter").mkdir(exist_ok=True)

    for name in ("schemas",):
        source = project.root / name
        if source.is_dir():
            shutil.copytree(source, destination / name, dirs_exist_ok=True)
    for name in ("AGENT-GUIDE.md", "CHECKLIST.md"):
        source = project.root / name
        if not source.is_file():
            source = KIT / name
        if source.is_file():
            shutil.copy2(source, destination / name)

    (destination / "README.txt").write_text(_readme(project, builds, prepared), encoding="utf-8")
    _sums(destination)
    return destination


def _sums(root: Path) -> None:
    import hashlib

    lines = []
    for path in sorted(tree_files(root)):
        if path.name == "SHA256SUMS":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(root).as_posix()}")
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _readme(project, builds, prepared) -> str:
    lines = [
        f"{project.name}: a Horizon port",
        "",
        f"Made with HorizonPort. Minecraft {project.minecraft}, Launch API 0.1.x.",
        "",
        "This folder holds no Minecraft files and no prepared resources: the port",
        "makes them on the player's machine, once, from the player's own account.",
        "",
        "Builds pinned:",
    ]
    if builds:
        for item in builds:
            lines.append(
                f"  - {item['tag']}: {item['files']} files, {human_bytes(item['bytes'])}, "
                f"archive sha256 {item['archiveSha256'] or 'not recorded'}"
            )
    else:
        lines.append("  (none: run `horizonport fetch` before `horizonport bundle`)")
    lines += ["", "Prepared trees verified here (the player's own copy is made fresh):"]
    if prepared:
        for item in prepared:
            lines.append(f"  - {item['key']}: {item['files']} files, {human_bytes(item['bytes'])}, digest {item['digest'][:16]}...")
    else:
        lines.append("  (none yet)")
    lines += [
        "",
        "Install: copy adapter/ into your launcher, keep horizonport-bundle.json beside it,",
        "and check every file against SHA256SUMS before shipping.",
        "",
    ]
    return "\n".join(lines)
