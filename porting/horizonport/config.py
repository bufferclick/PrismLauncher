"""`port.config.json`: the one file that describes a port.

A port project is a folder holding this file, an instance folder, the
content-addressed store and the launcher adapter. Everything the toolkit does
reads from here, so a launcher can commit the config and treat the rest
(store, instances, secrets) as machine-local data.

Unknown keys are refused on purpose, as the engine's manifests do: a typo in
`policy.requireSignature` must fail loudly rather than silently disable the
signature check.
"""

from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import SCHEMA_STAMP, PortError, default_data_home, now_utc, read_json, write_json

CONFIG_NAME = "port.config.json"
TOP_LEVEL = {
    "horizonport",
    "name",
    "description",
    "engine",
    "minecraft",
    "paths",
    "launch",
    "adapter",
    "policy",
    "auth",
    "keys",
    "created",
}

DEFAULTS: dict[str, Any] = {
    "horizonport": 1,
    "name": "MyLauncher",
    "description": "A launcher that plays Horizon.",
    "engine": {"repo": "horizon-rust/horizon", "tag": "nightly", "commit": None},
    "minecraft": "26.3",
    "paths": {"data": ".horizonport"},
    "launch": {"width": 1280, "height": 720, "fullscreen": False},
    "adapter": {"kind": "node", "entry": "adapter/index.mjs"},
    "auth": {"clientId": None},
    "policy": {
        "requireSignature": True,
        "ownerGate": True,
        "telemetry": False,
        "keepBuilds": 2,
    },
    "keys": None,
    "created": None,
}

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_MINECRAFT = re.compile(r"^[0-9]+(\.[0-9]+){0,3}$")


@dataclass
class PortProject:
    """A port project on disk, with every path resolved."""

    root: Path
    config: dict[str, Any]

    @property
    def config_path(self) -> Path:
        return self.root / CONFIG_NAME

    @property
    def name(self) -> str:
        return self.config["name"]

    @property
    def minecraft(self) -> str:
        return self.config["minecraft"]

    @property
    def engine(self) -> dict[str, Any]:
        return self.config["engine"]

    @property
    def policy(self) -> dict[str, Any]:
        return self.config["policy"]

    @property
    def launch_defaults(self) -> dict[str, Any]:
        return self.config["launch"]

    @property
    def data(self) -> Path:
        raw = Path(self.config["paths"]["data"]).expanduser()
        return raw if raw.is_absolute() else (self.root / raw)

    @property
    def store(self) -> Path:
        return self.data / "store"

    @property
    def builds(self) -> Path:
        return self.store / "builds"

    @property
    def prepared(self) -> Path:
        return self.store / "prepared"

    @property
    def mojang(self) -> Path:
        return self.store / "mojang"

    @property
    def instances(self) -> Path:
        return self.data / "instances"

    @property
    def secrets(self) -> Path:
        return self.data / "secrets"

    @property
    def state_path(self) -> Path:
        return self.data / "state.json"

    @property
    def adapter_entry(self) -> Path | None:
        entry = self.config.get("adapter", {}).get("entry")
        return (self.root / entry) if entry else None

    def save(self) -> None:
        write_json(self.config_path, self.config)

    def ensure_data(self) -> None:
        for path in (self.data, self.store, self.builds, self.prepared, self.mojang, self.instances, self.secrets):
            path.mkdir(parents=True, exist_ok=True)

    # -- loading -----------------------------------------------------------
    @classmethod
    def load(cls, start: Path | str = ".", *, required: bool = True) -> "PortProject":
        root = find_root(Path(start))
        if root is None:
            if not required:
                return cls(root=Path(start).resolve(), config=copy.deepcopy(DEFAULTS))
            raise PortError(
                f"no {CONFIG_NAME} here or in any folder above {Path(start).resolve()}",
                hint="Run `horizonport init PATH` to make a port project.",
                code=2,
            )
        config = read_json(root / CONFIG_NAME)
        project = cls(root=root, config=merge_defaults(config))
        problems = project.problems()
        if problems:
            raise PortError(
                f"{root / CONFIG_NAME} is not a valid port config:\n  - " + "\n  - ".join(problems)
            )
        return project

    @classmethod
    def create(cls, root: Path, *, name: str | None = None) -> "PortProject":
        root = root.resolve()
        if (root / CONFIG_NAME).exists():
            raise PortError(f"{root / CONFIG_NAME} already exists")
        config = copy.deepcopy(DEFAULTS)
        if name:
            config["name"] = name
        config["created"] = now_utc()
        project = cls(root=root, config=config)
        problems = project.problems()
        if problems:
            raise PortError("that name is not usable:\n  - " + "\n  - ".join(problems))
        root.mkdir(parents=True, exist_ok=True)
        project.save()
        project.ensure_data()
        return project

    # -- validation --------------------------------------------------------
    def problems(self) -> list[str]:
        """Every reason this config would mislead a launcher, in plain words."""
        config = self.config
        found: list[str] = []
        unknown = sorted(set(config) - TOP_LEVEL)
        if unknown:
            found.append(f"unknown key(s) {', '.join(unknown)}; see porting/contract.md")
        for key in sorted(TOP_LEVEL - set(config)):
            found.append(f"missing key `{key}`")
        if config.get("horizonport") != 1:
            found.append("`horizonport` must be 1 (this toolkit reads schema 1)")
        name = config.get("name")
        if not isinstance(name, str) or not _NAME.match(name):
            found.append("`name` must be 1-64 characters of letters, digits, space, `_`, `.` or `-`")
        engine = config.get("engine")
        if not isinstance(engine, dict):
            found.append("`engine` must be an object")
        else:
            extra = sorted(set(engine) - {"repo", "tag", "commit"})
            if extra:
                found.append(f"unknown engine key(s) {', '.join(extra)}")
            if not isinstance(engine.get("repo"), str) or not _REPO.match(engine.get("repo", "")):
                found.append("`engine.repo` must look like `owner/repository`")
            tag = engine.get("tag")
            if tag is not None and (not isinstance(tag, str) or not tag.strip()):
                found.append("`engine.tag` must be a tag name or null")
            commit = engine.get("commit")
            if commit is not None and not re.fullmatch(r"[0-9a-f]{40}", str(commit)):
                found.append("`engine.commit` must be 40 lowercase hex characters or null")
        if not isinstance(config.get("minecraft"), str) or not _MINECRAFT.match(config.get("minecraft", "")):
            found.append("`minecraft` must be a version such as \"26.3\"")
        paths = config.get("paths")
        if not isinstance(paths, dict) or set(paths) != {"data"}:
            found.append("`paths` must hold exactly `data`")
        elif not isinstance(paths["data"], str) or not paths["data"].strip():
            found.append("`paths.data` must be a folder")
        launch = config.get("launch")
        if not isinstance(launch, dict) or set(launch) != {"width", "height", "fullscreen"}:
            found.append("`launch` must hold exactly `width`, `height` and `fullscreen`")
        else:
            for key in ("width", "height"):
                value = launch[key]
                if not isinstance(value, int) or isinstance(value, bool) or not 320 <= value <= 16384:
                    found.append(f"`launch.{key}` must be a whole number from 320 to 16384")
            if not isinstance(launch["fullscreen"], bool):
                found.append("`launch.fullscreen` must be true or false")
        adapter = config.get("adapter")
        if not isinstance(adapter, dict) or set(adapter) != {"kind", "entry"}:
            found.append("`adapter` must hold exactly `kind` and `entry`")
        else:
            if adapter["kind"] not in ("node", "rust", "python", "none"):
                found.append("`adapter.kind` must be node, rust, python or none")
            if adapter["entry"] is not None and not isinstance(adapter["entry"], str):
                found.append("`adapter.entry` must be a path or null")
        policy = config.get("policy")
        wanted = {"requireSignature", "ownerGate", "telemetry", "keepBuilds"}
        if not isinstance(policy, dict) or set(policy) != wanted:
            found.append("`policy` must hold exactly requireSignature, ownerGate, telemetry and keepBuilds")
        else:
            for key in ("requireSignature", "ownerGate", "telemetry"):
                if not isinstance(policy[key], bool):
                    found.append(f"`policy.{key}` must be true or false")
            builds = policy["keepBuilds"]
            if not isinstance(builds, int) or isinstance(builds, bool) or not 1 <= builds <= 20:
                found.append("`policy.keepBuilds` must be a whole number from 1 to 20")
        auth_block = config.get("auth")
        if not isinstance(auth_block, dict) or set(auth_block) != {"clientId"}:
            found.append("`auth` must hold exactly `clientId`")
        else:
            client_id = auth_block["clientId"]
            if client_id is not None and not re.fullmatch(
                r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", str(client_id)
            ):
                found.append("`auth.clientId` must be your Azure app's Application (client) ID or null")
        if config.get("keys") is not None and not isinstance(config["keys"], str):
            found.append("`keys` must be a path to a key file or null")
        return found

    @property
    def client_id(self) -> str | None:
        value = self.config.get("auth", {}).get("clientId")
        return str(value) if value else os.environ.get("HORIZONPORT_CLIENT_ID") or None

    def key_file(self) -> Path | None:
        raw = self.config.get("keys")
        if not raw:
            return None
        path = Path(raw).expanduser()
        return path if path.is_absolute() else self.root / path

    def describe(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_STAMP,
            "root": str(self.root),
            "config": str(self.config_path),
            "data": str(self.data),
            "store": str(self.store),
            "instances": str(self.instances),
            "engine": self.config["engine"],
            "minecraft": self.minecraft,
        }


def merge_defaults(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise PortError(f"{CONFIG_NAME} must hold a JSON object")
    merged = copy.deepcopy(DEFAULTS)
    for key, value in config.items():
        if key in ("engine", "paths", "launch", "adapter", "policy", "auth") and isinstance(value, dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def find_root(start: Path) -> Path | None:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / CONFIG_NAME).is_file():
            return candidate
    return None


def suggested_data_dir() -> str:
    return str(default_data_home())


def env_override() -> Path | None:
    raw = os.environ.get("HORIZONPORT_DATA")
    return Path(raw).expanduser() if raw else None
