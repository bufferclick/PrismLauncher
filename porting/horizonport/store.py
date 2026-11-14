"""The content-addressed store: everything HorizonPort downloads exactly once.

Layout under `<data>/store/`:

    builds/<tag>/                 an unpacked Horizon build (client, preparer, lock, exporters)
    prepared/<key>/               horizon-prepare's output, one per (build, Minecraft, layout)
    mojang/<minecraft>/           the owner's game files a preparation reads
    index.json                    what each entry is, its digest, size and refs
    tmp/                          staging; a folder reaches its final name only when complete

`prepared/<key>` is the answer to "download the assets once": the key covers
the build's commit, the preparer's `output_version` and the Minecraft version,
so every instance of the same engine reuses the same folder and a new instance
costs a `--check` (a few hundred milliseconds), not a download.

`index.json` records a tree digest for each entry. `horizonport store verify`
recomputes it; the launcher runs the engine's own `--check` before each start,
which is what actually protects a player from a half-written folder.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .util import (
    PortError,
    digest_tree,
    human_bytes,
    now_utc,
    read_json,
    remove_tree,
    tree_files,
    write_json,
)

STATE_SCHEMA = 1


@dataclass
class Entry:
    key: str
    kind: str
    path: str
    digest: str = ""
    files: int = 0
    bytes: int = 0
    created: str = field(default_factory=now_utc)
    verified: str | None = None
    refs: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "kind": self.kind,
            "path": self.path,
            "digest": self.digest,
            "files": self.files,
            "bytes": self.bytes,
            "created": self.created,
            "verified": self.verified,
            "refs": self.refs,
        }
        value.update(self.extra)
        return value

    @classmethod
    def from_json(cls, key: str, value: dict[str, Any]) -> "Entry":
        known = {"kind", "path", "digest", "files", "bytes", "created", "verified", "refs"}
        missing = {"kind", "path"} - set(value)
        if missing:
            raise PortError(f"store entry {key} lacks {', '.join(sorted(missing))}")
        return cls(
            key=key,
            kind=value["kind"],
            path=value["path"],
            digest=value.get("digest", ""),
            files=int(value.get("files", 0)),
            bytes=int(value.get("bytes", 0)),
            created=value.get("created", ""),
            verified=value.get("verified"),
            refs=list(value.get("refs", [])),
            extra={k: v for k, v in value.items() if k not in known},
        )


class Store:
    def __init__(self, project):
        self.project = project
        self.path = project.data / "store"
        self.index_path = self.path / "index.json"
        self.entries: dict[str, Entry] = {}
        self.load()

    # -- persistence -------------------------------------------------------
    def load(self) -> None:
        if not self.index_path.exists():
            return
        raw = read_json(self.index_path)
        if raw.get("schema") != STATE_SCHEMA:
            raise PortError(
                f"{self.index_path} has schema {raw.get('schema')!r}; this toolkit reads {STATE_SCHEMA}",
                hint="Delete the store and download the build again.",
            )
        for key, value in raw.get("entries", {}).items():
            self.entries[key] = Entry.from_json(key, value)

    def save(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        write_json(
            self.index_path,
            {
                "schema": STATE_SCHEMA,
                "updated": now_utc(),
                "entries": {key: self.entries[key].to_json() for key in sorted(self.entries)},
            },
        )

    # -- entries -----------------------------------------------------------
    def entry_path(self, entry: Entry) -> Path:
        return self.project.data / entry.path

    def get(self, key: str) -> Entry:
        entry = self.entries.get(key)
        if entry is None:
            raise PortError(
                f"the store has no {key}",
                hint="Run `horizonport fetch` (for a build) or `horizonport prepare` (for resources).",
            )
        return entry

    def find(self, key: str) -> Entry | None:
        return self.entries.get(key)

    def put(self, entry: Entry, *, directory: Path | None = None) -> Entry:
        """Record an entry whose folder is already in place, measuring it."""
        if directory is None:
            directory = self.entry_path(entry)
        if not directory.is_dir():
            raise PortError(f"{directory} is not a folder")
        digest, files, size = digest_tree(directory)
        entry.digest = digest
        entry.files = files
        entry.bytes = size
        entry.verified = now_utc()
        entry.path = self._relative(directory)
        self.entries[entry.key] = entry
        self.save()
        return entry

    def remove(self, key: str, *, delete: bool = True) -> None:
        entry = self.entries.pop(key, None)
        if entry is None:
            return
        if delete:
            remove_tree(self.entry_path(entry))
        self.save()

    def of_kind(self, kind: str) -> list[Entry]:
        return [entry for entry in self.entries.values() if entry.kind == kind]

    def builds(self) -> list[Entry]:
        return self.of_kind("build")

    def prepared(self) -> list[Entry]:
        return self.of_kind("prepared")

    # -- verification ------------------------------------------------------
    def verify(self, entry: Entry, *, full: bool = True) -> tuple[bool, str]:
        directory = self.entry_path(entry)
        if not directory.is_dir():
            return False, f"{entry.key}: {directory} is missing"
        if not full:
            present = sum(1 for _ in tree_files(directory))
            if present != entry.files:
                return False, f"{entry.key}: {present} files, {entry.files} recorded"
            return True, f"{entry.key}: {entry.files} files present"
        digest, files, size = digest_tree(directory)
        if digest != entry.digest:
            return False, (
                f"{entry.key}: contents changed ({files} files, {human_bytes(size)}; "
                f"recorded {entry.files}, {human_bytes(entry.bytes)})"
            )
        entry.verified = now_utc()
        self.save()
        return True, f"{entry.key}: {files} files, {human_bytes(size)}"

    def references(self) -> dict[str, list[str]]:
        """Which instance uses which store key, straight from the instances."""
        found: dict[str, list[str]] = {}
        instances = self.project.instances
        if not instances.is_dir():
            return found
        for instance_file in sorted(instances.glob("*/instance.json")):
            try:
                data = read_json(instance_file)
            except PortError:
                continue
            refs = [f"instance:{data.get('name', instance_file.parent.name)}"]
            build = data.get("build")
            if isinstance(build, str) and build:
                found.setdefault(build_key(build), []).extend(refs)
            prepared = data.get("prepared")
            if isinstance(prepared, str) and prepared:
                found.setdefault(prepared, []).extend(refs)
        return found

    def gc(self, *, dry_run: bool = False) -> list[str]:
        """Remove what nothing uses, keeping rollback room.

        Kept: every entry an instance points at, the newest `policy.keepBuilds`
        builds (so a rollback still works), the build the config pins, and the
        owner's game files. Prepared trees are kept only while an instance
        reads them: they are the large entries, and preparing again is minutes,
        not a download.
        """
        refs = self.references()
        keep = self._rollback_builds()
        removed: list[str] = []
        for key in sorted(self.entries):
            entry = self.entries[key]
            if key in refs:
                entry.refs = refs[key]
                continue
            entry.refs = []
            if entry.kind == "mojang" or key in keep:
                continue
            removed.append(key)
            if not dry_run:
                self.remove(key)
        if not dry_run and removed:
            self.save()
        return removed

    def _rollback_builds(self) -> set[str]:
        pinned = self.project.engine.get("tag") or ""
        builds = sorted(
            self.builds(),
            key=lambda entry: (entry.created, entry.key),
            reverse=True,
        )
        keep = {entry.key for entry in builds[: max(1, int(self.project.policy.get("keepBuilds", 2)))]}
        if pinned:
            keep.add(build_key(pinned))
        return keep

    def total_bytes(self) -> int:
        return sum(entry.bytes for entry in self.entries.values())

    def summarise(self) -> list[tuple[str, str, str]]:
        rows: list[tuple[str, str, str]] = []
        for key in sorted(self.entries):
            entry = self.entries[key]
            directory = self.entry_path(entry)
            status = "missing" if not directory.is_dir() else human_bytes(entry.bytes)
            rows.append((entry.kind, key, f"{status}, {entry.files} files"))
        return rows

    def staging(self, name: str) -> Path:
        path = self.path / "tmp" / name
        remove_tree(path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def install_staging(self, staging: Path, target: Path) -> None:
        """Move a finished staging folder into place, replacing an older copy."""
        target.parent.mkdir(parents=True, exist_ok=True)
        remove_tree(target)
        shutil.move(str(staging), str(target))

    def _relative(self, directory: Path) -> str:
        try:
            return directory.resolve().relative_to(self.project.data.resolve()).as_posix()
        except ValueError:
            return str(directory.resolve())


def build_key(tag: str) -> str:
    return f"build:{tag}"


def prepared_key(build: str, minecraft: str, output_version: str | int | None) -> str:
    """The identity of a prepared tree: same build, same layout, same game files."""
    layout = str(output_version) if output_version is not None else "unknown"
    return f"prepared:{build}@{minecraft}@{layout}"


def mojang_key(minecraft: str) -> str:
    return f"mojang:{minecraft}"


def prepare_ref(project, key: str) -> Path:
    entry = Store(project).get(key)
    return project.data / entry.path


def safe_members(names: Iterable[str]) -> list[str]:
    """Refuse archive entries that could write outside the destination."""
    bad: list[str] = []
    for name in names:
        parts = Path(name.replace("\\", "/")).parts
        if not name or name.startswith(("/", "\\")) or ".." in parts or (parts and ":" in parts[0]):
            bad.append(name)
    return bad
