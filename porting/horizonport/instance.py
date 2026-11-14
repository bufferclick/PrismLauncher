"""Horizon instances: one game folder per world set, sharing one prepared tree.

An instance is a folder with an `instance.json` in it. The game writes its
worlds, options and packs into `game/` (`--game-dir`) and its logs and crash
reports into `home/` (`--home`), which is exactly the split the Launch API
defines. Nothing else is per-instance: the build and the prepared resources are
shared, so a second instance of the same build costs no download.

`instance.json` is what the launcher lists, not what the game reads. A port can
keep its own database and still use this file as the source of truth for "which
build, which prepared tree, which mods".
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .util import PortError, now_utc, read_json, remove_tree, write_json

SCHEMA = 1
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")


@dataclass
class Instance:
    project: Any
    name: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def folder(self) -> Path:
        return self.project.instances / self.name

    @property
    def file(self) -> Path:
        return self.folder / "instance.json"

    @property
    def game(self) -> Path:
        return self.folder / "game"

    @property
    def home(self) -> Path:
        return self.folder / "home"

    @property
    def mods_dir(self) -> Path:
        return self.game / "horizon-mods"

    @property
    def build_tag(self) -> str:
        return str(self.data.get("build", ""))

    @property
    def prepared_key(self) -> str:
        return str(self.data.get("prepared", ""))

    @property
    def settings(self) -> dict[str, Any]:
        return self.data.setdefault("settings", {})

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        write_json(self.file, self.data)

    def ensure_folders(self) -> None:
        for path in (self.game, self.home, self.mods_dir, self.game / "saves", self.game / "resourcepacks", self.game / "shaderpacks"):
            path.mkdir(parents=True, exist_ok=True)
        self.save()

    def mark_played(self) -> None:
        self.data["lastPlayed"] = now_utc()
        self.data["playCount"] = int(self.data.get("playCount", 0)) + 1
        self.save()

    def add_mod(self, *, mod_id: str, file: str, version: str = "", enabled: bool = True) -> None:
        mods = [m for m in self.data.get("mods", []) if m.get("id") != mod_id]
        mods.append({"id": mod_id, "file": file, "version": version, "enabled": enabled})
        self.data["mods"] = sorted(mods, key=lambda m: str(m.get("id")))
        self.save()

    def mods(self) -> list[dict[str, Any]]:
        return list(self.data.get("mods", []))

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "folder": str(self.folder),
            "game": str(self.game),
            "home": str(self.home),
            "build": self.build_tag,
            "prepared": self.prepared_key,
            "lastPlayed": self.data.get("lastPlayed"),
            "playCount": self.data.get("playCount", 0),
            "mods": len(self.mods()),
        }


def validate_name(name: str) -> str:
    if not NAME.match(name or ""):
        raise PortError(
            f"{name!r} is not a usable instance name",
            hint="Use 1-64 characters: letters, digits, space, `_`, `.` or `-`.",
        )
    return name


def path_for(project, name: str) -> Path:
    return project.instances / validate_name(name)


def existing_names(project) -> list[str]:
    if not project.instances.is_dir():
        return []
    return sorted(p.name for p in project.instances.iterdir() if (p / "instance.json").is_file())


def load(project, name: str) -> Instance:
    folder = path_for(project, name)
    file = folder / "instance.json"
    if not file.is_file():
        available = ", ".join(existing_names(project)) or "none"
        raise PortError(
            f"there is no instance called {name!r}",
            hint=f"Instances here: {available}. Make one with `horizonport instance new {name}`.",
        )
    data = read_json(file)
    if data.get("schema") != SCHEMA:
        raise PortError(f"{file} has schema {data.get('schema')!r}; this toolkit reads {SCHEMA}")
    data.setdefault("name", name)
    if data["name"] != name:
        raise PortError(f"{file} says it is {data['name']!r}, but its folder is {name!r}")
    return Instance(project=project, name=name, data=data)


def create(
    project,
    name: str,
    *,
    build: str,
    prepared: str,
    settings: dict[str, Any] | None = None,
) -> Instance:
    validate_name(name)
    folder = project.instances / name
    lowered = name.lower()
    for other in existing_names(project):
        if other.lower() == lowered:
            raise PortError(f"an instance called {other!r} already exists (names differ by case only)")
    if folder.exists():
        raise PortError(f"{folder} already exists; remove it or choose another name")
    data = {
        "schema": SCHEMA,
        "name": name,
        "created": now_utc(),
        "lastPlayed": None,
        "playCount": 0,
        "build": build,
        "prepared": prepared,
        "settings": dict(settings or {}),
        "mods": [],
    }
    instance = Instance(project=project, name=name, data=data)
    instance.ensure_folders()
    return instance


def attach(project, name: str, *, build: str, prepared: str) -> Instance:
    """Point an instance at a build and a prepared tree (the add-instance step)."""
    instance = load(project, name)
    instance.data["build"] = build
    instance.data["prepared"] = prepared
    instance.save()
    return instance


def remove(project, name: str) -> Path:
    instance = load(project, name)
    folder = instance.folder
    shutil.rmtree(folder)
    return folder


def summaries(project) -> list[dict[str, Any]]:
    rows = []
    for name in existing_names(project):
        try:
            rows.append(load(project, name).describe())
        except PortError:
            rows.append({"name": name, "error": "instance.json is not readable"})
    return rows


def open_worlds(instance: Instance) -> list[str]:
    saves = instance.game / "saves"
    if not saves.is_dir():
        return []
    return sorted(p.name for p in saves.iterdir() if p.is_dir() and not p.name.startswith("."))
