"""The ten steps of a port, printable from the terminal.

`horizonport guide` is the same order as `PORTING.md` and `AGENT-GUIDE.md`, so
a developer, a script and an agent all follow one path.
"""

from __future__ import annotations

from pathlib import Path

KIT = Path(__file__).resolve().parents[1]

STEPS: list[tuple[int, str, str, str]] = [
    (1, "Install the kit", "git clone https://github.com/bufferclick/horizonIMPORTER && cd horizonIMPORTER", "porting/horizonport on this machine"),
    (2, "Check the machine", "python3 -m porting.horizonport doctor", "every FAIL gone"),
    (3, "Make the port project", "python3 -m porting.horizonport init ~/MyLauncher --name \"My Launcher\"", "port.config.json, adapter/, schemas/"),
    (4, "Fetch a build", "python3 -m porting.horizonport fetch --tag nightly", "a signed build in store/builds/nightly"),
    (5, "Register sign-in", "create an Azure app, then: horizonport auth sign-in --client-id <GUID>", "a session for an account that owns the game"),
    (6, "Prepare once", "horizonport prepare --download        (or --from-install PATH)", "store/prepared/<key> with every file"),
    (7, "Add the first instance", "horizonport instance new Work", "instances/Work/{instance.json,game,home}"),
    (8, "Play", "horizonport play Work", "the game window, and an exit code your launcher reports"),
    (9, "Mods", "horizonport mod new my-mod && horizonport mod build my-mod && horizonport mod install my-mod/target/horizon-mod/my_mod.hmod --instance Work", "a .hmod the game loads"),
    (10, "Ship", "horizonport check --full && horizonport bundle", "dist/horizonport-bundle with SHA256SUMS"),
]

DOCS = {
    "handbook": "PORTING.md",
    "agent": "AGENT-GUIDE.md",
    "checklist": "CHECKLIST.md",
    "contract": "contract.md",
    "assets": "assets.md",
    "auth": "auth.md",
    "launch": "launch.md",
    "mods": "mods.md",
    "faq": "faq.md",
}


def render() -> str:
    lines = ["HorizonPort: ten steps from a repository to a launcher that plays Horizon.", ""]
    width = max(len(title) for _, title, _, _ in STEPS)
    for number, title, command, result in STEPS:
        lines.append(f"{number:>2}. {title.ljust(width)}  {command}")
        lines.append(f"    {' ' * width}  -> {result}")
    lines += ["", "Then read PORTING.md end to end; it answers the questions the steps raise.", ""]
    lines.append("Docs in this kit:")
    for name, file in DOCS.items():
        lines.append(f"  {name:<10} porting/{file}")
    return "\n".join(lines)


def path_for(name: str) -> Path | None:
    """Where a doc is: the kit first, then the repository root (the handbook lives there)."""
    file = DOCS.get(name, name)
    for base in (KIT, KIT.parent):
        candidate = base / file
        if candidate.is_file():
            return candidate
    return None
