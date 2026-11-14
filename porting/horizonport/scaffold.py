"""`horizonport init`: a port project that is ready for a launcher.

What it writes:

    port.config.json     the port's identity and policy
    .gitignore           the store, instances and secrets stay out of Git
    README.md            how this project is built and played, for its maintainers
    adapter/             the launcher adapter matching `adapter.kind`
    schemas/             JSON Schemas for every file the port writes
    AGENT-GUIDE.md       the playbook to hand to an AI agent
    CHECKLIST.md         the seven gates, with a box each

Nothing here downloads a build or touches the player's files; `init` is safe to
run anywhere, and re-running it refuses to overwrite an existing project.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .config import PortProject
from .util import PortError

KIT = Path(__file__).resolve().parents[1]
TEMPLATES = KIT / "templates"
SCHEMAS = KIT / "schemas"
DOCS = KIT

GITIGNORE = """\
# HorizonPort: machine-local data, never committed.
.horizonport/
dist/
*.hmod
"""

README = """\
# {name}

A Horizon launcher port, made with [HorizonPort](../porting/README.md).

    horizonport doctor                       # is this machine ready?
    horizonport fetch                        # install the pinned Horizon build
    horizonport prepare                      # prepare resources once (minutes)
    horizonport instance new Work            # first instance: reuses the prepared tree
    horizonport play Work                    # start the game

The complete handbook is `PORTING.md` in the HorizonPort kit; the playbook for
an AI agent is `AGENT-GUIDE.md`, copied here so an agent can read it in place.

Files here:

- `port.config.json` — the port's engine pin, Minecraft version, policy.
- `adapter/` — the launcher side: sign-in, "add instance", "Play".
- `schemas/` — the JSON shapes this port writes (`instance.json`, launch plan, bundle).
- The store, instances and secrets live in `.horizonport/` and are not committed.
"""


def init(
    root: Path,
    *,
    name: str | None = None,
    adapter: str = "node",
    force: bool = False,
) -> PortProject:
    root = root.expanduser().resolve()
    config = root / "port.config.json"
    if config.exists():
        if not force:
            raise PortError(
                f"{config} already exists",
                hint="Pick another folder, or pass --force to rewrite the files around it.",
                code=2,
            )
        project = PortProject.load(root)
    else:
        project = PortProject.create(root, name=name)
    project.config["adapter"]["kind"] = adapter
    project.config["adapter"]["entry"] = None if adapter == "none" else _entry_for(adapter)
    project.save()
    project.ensure_data()

    (root / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (root / "README.md").write_text(README.format(name=project.name), encoding="utf-8")
    _copy_tree(SCHEMAS, root / "schemas")
    for doc in ("AGENT-GUIDE.md", "CHECKLIST.md"):
        source = _doc(doc)
        if source is not None:
            shutil.copy2(source, root / doc)
    if adapter in ("node", "rust", "python"):
        _copy_tree(TEMPLATES / f"adapter-{adapter}", root / "adapter")
    return project


def _doc(name: str) -> Path | None:
    for base in (DOCS, DOCS.parent):
        candidate = base / name
        if candidate.is_file():
            return candidate
    return None


def _entry_for(adapter: str) -> str:
    return {"node": "adapter/index.mjs", "rust": "adapter/src/lib.rs", "python": "adapter/adapter.py"}[adapter]


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        return
    for path in sorted(source.rglob("*")):
        if "__pycache__" in path.parts:
            continue
        target = destination / path.relative_to(source)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
