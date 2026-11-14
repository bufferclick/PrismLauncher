"""Content mods: scaffold, build, check and install `.hmod` files.

A content mod is a zip of `horizon-mod.toml` + `assets/` + `data/` with no code
(`docs/api/mod-files.md`). The game reads it from `horizon-mods/` in the game
folder and turns it on with `mod.<id>:true` in `horizon-mods.txt` — the same
files the engine's own Mods screen writes, so a port that writes them shows up
in the game's Options > Mods and vice versa.

The builder makes deterministic archives and enforces the limits the engine
enforces, so a mod that `horizonport mod build` accepts is one the game loads.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import re
import tomllib
import zipfile
from pathlib import Path
from typing import Any

from .util import PortError, human_bytes, info, read_text, sha256_file, write_json

ID = re.compile(r"^[a-z0-9_]{1,64}$")
LOCATION = re.compile(r"^[a-z0-9_.-]+$")
ALLOWED_MANIFEST = {
    "id",
    "name",
    "version",
    "description",
    "authors",
    "api",
    "side",
    "capabilities",
    "namespaces",
    "experimental",
}
CAPABILITIES = {
    "game-read",
    "chat",
    "hud",
    "storage",
    "command",
    "registries",
    "ui",
    "render",
    "input",
    "players",
    "world",
    "recipes",
}
SIDES = {"client", "server", "both"}
MAX_FILES = 65_536
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024


# ---------------------------------------------------------------------------
# Scaffold
# ---------------------------------------------------------------------------
MANIFEST_TEMPLATE = """\
# A content mod for Horizon (docs/mods.md). No code: blocks, items, recipes,
# loot, models and textures, read by the game from `data/` and `assets/`.
id = "{id}"
name = "{name}"
version = "0.1.0"
description = "A block, and the files that make it show up."
authors = ["You"]
api = "0.2"                      # content mods speak 0.2
side = "both"                    # a server with this mod accepts clients that have it
capabilities = ["registries"]    # it adds blocks and items
namespaces = []
"""

BLOCK_TEMPLATE = """\
{
  "template": "minecraft:stone",
  "properties": { "hardness": 1.5, "sounds": "minecraft:stone" },
  "item": true
}
"""

MODEL_TEMPLATE = """\
{ "parent": "minecraft:block/stone" }
"""

README_TEMPLATE = """\
# {name}

A Horizon content mod, made with HorizonPort.

    horizonport mod build .          # writes target/horizon-mod/{id}.hmod
    horizonport mod check target/horizon-mod/{id}.hmod
    horizonport mod install target/horizon-mod/{id}.hmod --instance YOUR_INSTANCE

Edit `data/{id}/horizon/block/example_block.json` to change the block, add files
under `data/{id}/` for recipes, loot and tags, and under `assets/{id}/` for
models, textures and translations. The manifest's `id` decides both folders'
names. Turn it on in the game under Options > Mods, or with
`horizonport mod enable {id} --instance YOUR_INSTANCE`.
"""


def new(path: Path, *, name: str | None = None, mod_id: str | None = None) -> Path:
    path = path.expanduser().resolve()
    if path.exists() and any(path.iterdir()):
        raise PortError(f"{path} is not empty")
    mod_id = mod_id or _slug(path.name)
    if not ID.match(mod_id):
        raise PortError(
            f"{mod_id!r} is not a mod id",
            hint="Use 1-64 characters of a-z, 0-9 and _ (the manifest's `id` rule).",
        )
    name = name or path.name.replace("-", " ").replace("_", " ").title()
    (path / "data" / mod_id / "horizon" / "block").mkdir(parents=True, exist_ok=True)
    (path / "assets" / mod_id / "models" / "item").mkdir(parents=True, exist_ok=True)
    (path / "horizon-mod.toml").write_text(
        MANIFEST_TEMPLATE.format(id=mod_id, name=name), encoding="utf-8"
    )
    (path / "data" / mod_id / "horizon" / "block" / "example_block.json").write_text(
        BLOCK_TEMPLATE, encoding="utf-8"
    )
    (path / "assets" / mod_id / "models" / "item" / "example_block.json").write_text(
        MODEL_TEMPLATE, encoding="utf-8"
    )
    (path / "assets" / mod_id / "lang").mkdir(parents=True, exist_ok=True)
    (path / "assets" / mod_id / "lang" / "en_us.json").write_text(
        '{\n  "block.' + mod_id + '.example_block": "' + name + ' Block"\n}\n',
        encoding="utf-8",
    )
    (path / "README.md").write_text(README_TEMPLATE.format(id=mod_id, name=name), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
def read_manifest(text: str) -> dict[str, Any]:
    try:
        manifest = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise PortError(f"horizon-mod.toml is not valid TOML: {exc}") from None
    problems = manifest_problems(manifest)
    if problems:
        raise PortError("horizon-mod.toml is not valid:\n  - " + "\n  - ".join(problems))
    return manifest


def manifest_problems(manifest: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    unknown = sorted(set(manifest) - ALLOWED_MANIFEST)
    if unknown:
        problems.append(f"unknown key(s) {', '.join(unknown)}; the game refuses the whole mod")
    for key in ("id", "name", "version", "api"):
        if not manifest.get(key):
            problems.append(f"`{key}` is required")
    if manifest.get("id") and not ID.match(str(manifest["id"])):
        problems.append("`id` must be 1-64 characters of a-z, 0-9 and _")
    if manifest.get("api") and str(manifest["api"]) != "0.2":
        problems.append('content mods speak api = "0.2"')
    side = manifest.get("side", "client")
    if side not in SIDES:
        problems.append(f'`side` must be one of {", ".join(sorted(SIDES))}')
    if side == "both" and "registries" not in _list(manifest.get("capabilities")):
        problems.append('a `side = "both"` content mod must list capability `registries`')
    if "registries" not in _list(manifest.get("capabilities")):
        problems.append('a content mod needs capability `registries` (it carries assets/ and data/)')
    for name in _list(manifest.get("capabilities")) + _list(manifest.get("experimental")):
        if name not in CAPABILITIES:
            problems.append(f"`{name}` is not a capability")
    for name in _list(manifest.get("namespaces")):
        if not ID.match(str(name)):
            problems.append(f"`namespaces`: {name!r} is not a namespace")
    if not isinstance(manifest.get("authors", []), list):
        problems.append("`authors` must be a list")
    return problems


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


# ---------------------------------------------------------------------------
# Content paths
# ---------------------------------------------------------------------------
def content_problems(name: str) -> list[str]:
    """Why the engine would refuse this path inside a content mod."""
    problems: list[str] = []
    if name.startswith("/") or "\\" in name or ":" in name:
        problems.append(f"{name}: must be a relative /-separated path")
        return problems
    parts = name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        problems.append(f"{name}: has an empty, `.` or `..` part")
        return problems
    root = parts[0]
    if root not in ("assets", "data"):
        problems.append(f"{name}: a content mod holds only assets/ and data/")
        return problems
    if len(parts) < 4:
        problems.append(f"{name}: needs <assets|data>/<namespace>/<folder>/<file>")
        return problems
    for part in parts[1:]:
        if part.endswith("/"):
            continue
        if not LOCATION.match(part.lower()) or part != part.lower():
            problems.append(f"{name}: {part!r} is not a lowercase [a-z0-9_.-] name")
    return problems


# ---------------------------------------------------------------------------
# Build and check
# ---------------------------------------------------------------------------
def build(folder: Path, *, output: Path | None = None) -> dict[str, Any]:
    folder = folder.expanduser().resolve()
    manifest_path = folder / "horizon-mod.toml"
    if not manifest_path.is_file():
        raise PortError(
            f"{folder} has no horizon-mod.toml",
            hint="Run `horizonport mod new PATH` to make a content mod.",
        )
    manifest = read_manifest(read_text(manifest_path))
    mod_id = str(manifest["id"])
    entries = _content_files(folder)
    if not entries:
        raise PortError(f"{folder} has no assets/ or data/ files to pack")
    _check_limits(entries)

    destination = output or (folder / "target" / "horizon-mod" / f"{mod_id}.hmod")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = destination.with_name(destination.name + ".part")
    with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        _write(archive, "horizon-mod.toml", manifest_path.read_bytes())
        for name, path in entries:
            _write(archive, name, path.read_bytes())
    import os

    os.replace(staged, destination)
    return {
        "mod": mod_id,
        "version": str(manifest["version"]),
        "file": str(destination),
        "size": destination.stat().st_size,
        "files": len(entries) + 1,
        "sha256": sha256_file(destination),
    }


def check(file: Path) -> dict[str, Any]:
    file = file.expanduser().resolve()
    if not file.is_file():
        raise PortError(f"{file} does not exist")
    if file.stat().st_size > 64 * 1024 * 1024:
        raise PortError(f"{file.name} is larger than the registry's 64 MiB limit")
    try:
        with zipfile.ZipFile(file) as archive:
            names = archive.namelist()
            problems: list[str] = []
            if "horizon-mod.toml" not in names:
                problems.append("no horizon-mod.toml: this is not a content mod")
            for name in names:
                if name == "horizon-mod.toml":
                    continue
                problems.extend(content_problems(name))
            counts = Counter(names)
            duplicated = sorted(name for name, seen in counts.items() if seen > 1)
            if duplicated:
                problems.append(f"the archive holds {', '.join(duplicated)} more than once")
            manifest: dict[str, Any] = {}
            if "horizon-mod.toml" in names:
                manifest = read_manifest(archive.read("horizon-mod.toml").decode("utf-8"))
            total = sum(info_.file_size for info_ in archive.infolist())
    except zipfile.BadZipFile:
        raise PortError(f"{file.name} is not a zip archive") from None
    if total > MAX_TOTAL_BYTES:
        problems.append(f"content is {human_bytes(total)}, over the 512 MiB limit")
    if problems:
        raise PortError(f"{file.name} would not load:\n  - " + "\n  - ".join(problems[:20]))
    return {
        "file": str(file),
        "mod": str(manifest.get("id", "")),
        "name": str(manifest.get("name", "")),
        "version": str(manifest.get("version", "")),
        "api": str(manifest.get("api", "")),
        "side": str(manifest.get("side", "client")),
        "entries": len(names),
        "bytes": total,
        "sha256": sha256_file(file),
    }


def _content_files(folder: Path) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    problems: list[str] = []
    for root in ("assets", "data"):
        base = folder / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_dir():
                continue
            name = path.relative_to(folder).as_posix()
            problems.extend(content_problems(name))
            found.append((name, path))
    if problems:
        raise PortError("these files would not load:\n  - " + "\n  - ".join(problems[:20]))
    return found


def _check_limits(entries: list[tuple[str, Path]]) -> None:
    if len(entries) > MAX_FILES:
        raise PortError(f"{len(entries)} files is over the {MAX_FILES} content-mod limit")
    total = 0
    for name, path in entries:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise PortError(f"{name} is {human_bytes(size)}, over the 16 MiB per-file limit")
        total += size
    if total > MAX_TOTAL_BYTES:
        raise PortError(f"content is {human_bytes(total)}, over the 512 MiB limit")


def _write(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    """Add a file with fixed metadata, so two builds of the same mod are identical."""
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.external_attr = 0o644 << 16
    entry.create_system = 3
    archive.writestr(entry, data)


# ---------------------------------------------------------------------------
# Install and enable
# ---------------------------------------------------------------------------
def install(project, instance, file: Path, *, enable: bool = True) -> dict[str, Any]:
    report = check(file)
    target_dir = instance.mods_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / f"{report['mod']}.hmod"
    destination.write_bytes(file.expanduser().read_bytes())
    if enable:
        set_enabled(instance, str(report["mod"]), True)
    instance.add_mod(
        mod_id=str(report["mod"]),
        file=destination.name,
        version=str(report["version"]),
        enabled=enable,
    )
    report["installed"] = str(destination)
    return report


def set_enabled(instance, mod_id: str, enabled: bool) -> Path:
    path = instance.game / "horizon-mods.txt"
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    prefix = f"mod.{mod_id}:"
    value = f"{prefix}{'true' if enabled else 'false'}"
    replaced = False
    output: list[str] = []
    for line in lines:
        if line.startswith(prefix):
            if not replaced:
                output.append(value)
                replaced = True
            continue
        output.append(line)
    if not replaced:
        output.append(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    for mod in instance.data.get("mods", []):
        if mod.get("id") == mod_id:
            mod["enabled"] = enabled
    instance.save()
    return path


def enabled_map(instance) -> dict[str, bool]:
    path = instance.game / "horizon-mods.txt"
    result: dict[str, bool] = {}
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("mod.") or ":" not in line:
            continue
        name, value = line[4:].split(":", 1)
        result[name] = value.strip().lower() == "true"
    return result


def installed(instance) -> list[dict[str, Any]]:
    enabled = enabled_map(instance)
    rows: list[dict[str, Any]] = []
    if instance.mods_dir.is_dir():
        for path in sorted(instance.mods_dir.glob("*.hmod")):
            report: dict[str, Any] = {"file": path.name, "enabled": enabled.get(path.stem, False)}
            try:
                checked = check(path)
                report.update({"mod": checked["mod"], "version": checked["version"], "side": checked["side"]})
            except PortError as exc:
                report["error"] = exc.message
            rows.append(report)
    for folder in sorted(p for p in instance.mods_dir.glob("*") if p.is_dir() and (p / "horizon-mod.toml").is_file()):
        rows.append({"file": folder.name + "/", "mod": folder.name, "enabled": enabled.get(folder.name, False), "folder": True})
    return rows


def registry_entry(report: dict[str, Any]) -> dict[str, Any]:
    """The shape a registry index lists for this file (docs/api/mod-index.md)."""
    return {
        "id": report["mod"],
        "version": report["version"],
        "sha256": report["sha256"],
        "size": report["size"] if "size" in report else report.get("bytes", 0),
        "side": report.get("side", "client"),
        "api": report.get("api", "0.2"),
    }


def write_registry_entry(report: dict[str, Any], path: Path) -> None:
    write_json(path, registry_entry(report))


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")[:64] or "my_mod"
