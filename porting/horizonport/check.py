"""`horizonport check`: would this port work for a player right now?

The seven gates every port passes before it ships (`porting/CHECKLIST.md`).
This command checks the mechanical ones and tells you the rest; it never
downloads anything and never starts the game.

    1. config      port.config.json parses and every key is known
    2. builds      each installed build has its programs and a Launch API answer
    3. resources   each prepared tree exists, matches its digest, holds files
    4. instances   every instance points at a build and a tree that exist
    5. mods        every installed .hmod passes the engine's content rules
    6. adapter     the launcher adapter the config names exists
    7. policy      signatures required, the owner gate on, telemetry off
"""

from __future__ import annotations

from pathlib import Path

from . import fetch, instance as instance_mod, mods
from .config import PortProject
from .store import Store
from .util import PortError, human_bytes, read_json

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def run(project: PortProject, *, full: bool = False) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    rows.extend(_config(project))
    try:
        store = Store(project)
    except PortError as exc:
        rows.append((FAIL, "store", exc.message))
        return rows
    rows.extend(_builds(store, full=full))
    rows.extend(_resources(store, full=full))
    rows.extend(_instances(project, store))
    rows.extend(_policy(project))
    return rows


def _config(project: PortProject) -> list[tuple[str, str, str]]:
    problems = project.problems()
    if problems:
        return [(FAIL, "config", problem) for problem in problems]
    return [(PASS, "config", f"{project.name} (schema {project.config['horizonport']})")]


def _builds(store: Store, *, full: bool) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    builds = store.builds()
    if not builds:
        rows.append((WARN, "builds", "none installed yet: `horizonport fetch --tag nightly`"))
        return rows
    for entry in builds:
        directory = store.entry_path(entry)
        if not directory.is_dir():
            rows.append((FAIL, entry.key, f"{directory} is missing"))
            continue
        missing = fetch.missing_programs(directory)
        if missing:
            rows.append((FAIL, entry.key, f"lacks {', '.join(missing)}"))
            continue
        api = entry.extra.get("launchApi")
        if not api:
            rows.append((WARN, entry.key, "no Launch API answer recorded; run `horizonport fetch` again"))
        else:
            rows.append((PASS, entry.key, f"Launch API {api.get('launch_api')}, Minecraft {api.get('minecraft')}"))
        if full:
            good, detail = store.verify(entry, full=True)
            rows.append((PASS if good else FAIL, entry.key + " digest", detail))
    return rows


def _resources(store: Store, *, full: bool) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for entry in store.prepared():
        directory = store.entry_path(entry)
        if not directory.is_dir():
            rows.append((FAIL, entry.key, f"{directory} is missing"))
            continue
        if not any(directory.iterdir()):
            rows.append((FAIL, entry.key, "the folder is empty"))
            continue
        if full:
            good, detail = store.verify(entry, full=True)
            rows.append((PASS if good else FAIL, entry.key, detail))
        else:
            rows.append((PASS, entry.key, f"{entry.files} files, {human_bytes(entry.bytes)}"))
    if not store.prepared():
        rows.append((WARN, "resources", "no prepared tree yet: `horizonport prepare`"))
    return rows


def _instances(project: PortProject, store: Store) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for summary in instance_mod.summaries(project):
        name = str(summary.get("name"))
        if "error" in summary:
            rows.append((FAIL, f"instance {name}", summary["error"]))
            continue
        try:
            instance = instance_mod.load(project, name)
        except PortError as exc:
            rows.append((FAIL, f"instance {name}", exc.message))
            continue
        build = store.find(f"build:{instance.build_tag}")
        prepared = store.find(instance.prepared_key)
        problems = []
        if build is None:
            problems.append(f"build {instance.build_tag!r} is not installed")
        if prepared is None:
            problems.append("prepared resources are missing")
        for required in (instance.game, instance.home):
            if not required.is_dir():
                problems.append(f"{required.name}/ is missing")
        if problems:
            rows.append((FAIL, f"instance {name}", "; ".join(problems)))
            continue
        rows.append(
            (
                PASS,
                f"instance {name}",
                f"{instance.build_tag}, {len(instance.mods())} mod(s), played {instance.data.get('playCount', 0)} time(s)",
            )
        )
        for mod in instance.mods_dir.glob("*.hmod"):
            try:
                report = mods.check(mod)
                rows.append((PASS, f"  mod {report['mod']}", f"{report['version']} ({report['side']})"))
            except PortError as exc:
                rows.append((FAIL, f"  mod {mod.name}", exc.message.splitlines()[0]))
    if not instance_mod.existing_names(project):
        rows.append((WARN, "instances", "none yet: `horizonport instance new Work --build nightly`"))
    return rows


def _policy(project: PortProject) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    policy = project.policy
    if policy.get("requireSignature"):
        rows.append((PASS, "policy: signatures", "builds must carry SHA256SUMS and a valid signature"))
    else:
        rows.append((FAIL, "policy: signatures", "requireSignature is false: a tampered build would install"))
    if policy.get("ownerGate"):
        rows.append((PASS, "policy: owner gate", "play needs an account that owns the game"))
    else:
        rows.append((FAIL, "policy: owner gate", "ownerGate is false: you would start the game for non-owners"))
    if policy.get("telemetry"):
        rows.append((WARN, "policy: telemetry", "on: the engine may send crash reports and benchmarks (docs/telemetry.md)"))
    else:
        rows.append((PASS, "policy: telemetry", "off: nothing leaves the player's machine"))
    adapter = project.adapter_entry
    if adapter is None or project.config["adapter"]["kind"] == "none":
        rows.append((WARN, "adapter", "none: the toolkit works, but the launcher UI is yours to write"))
    elif adapter.exists():
        rows.append((PASS, "adapter", str(adapter)))
    else:
        rows.append((FAIL, "adapter", f"{adapter} does not exist"))
    return rows


def render(rows: list[tuple[str, str, str]]) -> int:
    width = max((len(row[1]) for row in rows), default=10)
    for level, subject, detail in rows:
        print(f"{level:<5} {subject.ljust(width)}  {detail}")
    failures = sum(1 for row in rows if row[0] == FAIL)
    warnings = sum(1 for row in rows if row[0] == WARN)
    print(f"\n{len(rows) - failures - warnings} ok, {warnings} warning(s), {failures} failed")
    return 1 if failures else 0


def support_bundle(project: PortProject, destination: Path) -> Path:
    """What to ask a player for when something goes wrong (no tokens, no worlds)."""
    import json
    import platform

    destination.mkdir(parents=True, exist_ok=True)
    report = {
        "horizonport": 1,
        "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
        "config": project.config,
        "instances": instance_mod.summaries(project),
        "checks (without tokens)": [
            {"status": level, "what": subject, "detail": detail}
            for level, subject, detail in run(project)
        ],
    }
    path = destination / "horizonport-support.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path
