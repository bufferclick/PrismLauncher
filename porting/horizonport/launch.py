"""Play: build the launch plan, hand over the session, explain how it ended.

This is the last step of a port and the one players notice. The contract is the
engine's Launch API 0.1.0 (`docs/api/launch-reference.md`):

    horizon-client --resources PREPARED --game-dir GAME --home HOME \\
                   --width 1280 --height 720 --session-stdin

* the session JSON goes in on standard input (or a 0600 file the game deletes);
* only options the build lists in `--launch-api` may be passed — anything else
  is refused with exit code 2;
* exit 0 is a normal quit, 1 and 101 carry a crash report whose path is the
  last line on stderr, 2 means the launcher asked for something the build does
  not take.

`plan()` builds and validates the command without starting anything, which is
what `--dry-run` and a launcher's "show the command" button use.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import auth, fetch, prepare
from .store import Store
from .util import PortError, info, program_name, warn

EXIT_MEANINGS = {
    0: "the player quit",
    1: "the game stopped on an error; a crash report was saved",
    2: "the command line was refused; this is a bug in the launcher",
    101: "the game panicked; a crash report was saved",
}
CRASH_LINE = "Horizon: crash report saved to "


@dataclass
class LaunchPlan:
    argv: list[str]
    cwd: str
    instance: str
    game: str
    home: str
    resources: str
    session: str
    env: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "argv": self.argv,
            "cwd": self.cwd,
            "instance": self.instance,
            "game": self.game,
            "home": self.home,
            "resources": self.resources,
            "session": self.session,
            "env": self.env,
            "notes": self.notes,
        }


def plan(
    project,
    instance,
    *,
    session: str = "stdin",
    width: int | None = None,
    height: int | None = None,
    fullscreen: bool | None = None,
    world: str | None = None,
    server: str | None = None,
    extra: list[str] | None = None,
) -> LaunchPlan:
    """Validate and assemble the command a build accepts, without running it."""
    store = Store(project)
    build_entry = store.find(f"build:{instance.build_tag}")
    if build_entry is None:
        raise PortError(
            f"{instance.name} plays {instance.build_tag!r}, which is not installed",
            hint="Install it with `horizonport fetch`, or point the instance at another build.",
        )
    build_dir = store.entry_path(build_entry)
    prepared_entry = store.find(instance.prepared_key)
    if prepared_entry is None:
        raise PortError(
            f"{instance.name} has no prepared resources",
            hint=f"Run `horizonport prepare --build {instance.build_tag}`.",
        )
    resources = store.entry_path(prepared_entry)
    if not resources.is_dir():
        raise PortError(f"{resources} is missing; prepare the build again")

    api = fetch.check_launch_api(build_dir, build_entry.extra.get("launchApi"))
    supported = {str(option.get("name")) for option in api.get("options", []) if isinstance(option, dict)}
    if "--game-dir" not in supported or "--resources" not in supported:
        raise PortError(
            f"{instance.build_tag} speaks an older Launch API without --game-dir",
            hint="Install a newer build; HorizonPort needs Launch API 0.1.0.",
        )

    settings = instance.settings
    width = int(width or settings.get("width") or project.launch_defaults["width"])
    height = int(height or settings.get("height") or project.launch_defaults["height"])
    if fullscreen is None:
        fullscreen = bool(settings.get("fullscreen", project.launch_defaults["fullscreen"]))

    client = prepare.client(build_dir)
    argv = [
        str(client),
        "--resources",
        str(resources),
        "--game-dir",
        str(instance.game),
        "--home",
        str(instance.home),
        "--width",
        str(width),
        "--height",
        str(height),
    ]
    notes: list[str] = []

    def add(flag: str, *values: str) -> None:
        if flag not in supported:
            raise PortError(
                f"{instance.build_tag} does not take {flag}",
                hint="Update the build, or stop asking for that option.",
            )
        argv.extend([flag, *values])

    if fullscreen:
        add("--fullscreen")
    if session == "stdin":
        add("--session-stdin")
    elif session == "file":
        add("--session-file", "")
    else:
        raise PortError(f"unknown session transport {session!r}; use stdin or file")
    if world:
        if "/" in world or "\\" in world or world in (".", ".."):
            raise PortError("--world takes one folder name under saves/, not a path")
        add("--quickPlaySingleplayer", world)
    if server:
        add("--quickPlayMultiplayer", server)
    for argument in extra or []:
        flag = argument.split("=", 1)[0]
        if flag not in supported:
            raise PortError(
                f"{instance.build_tag} does not take {flag}",
                hint="Ask the build with `horizon-client --launch-api`; unlisted options are refused.",
            )
        argv.append(argument)
    env = {}
    if api.get("minecraft"):
        env["HORIZONPORT_MINECRAFT"] = str(api["minecraft"])
    return LaunchPlan(
        argv=argv,
        cwd=str(build_dir),
        instance=instance.name,
        game=str(instance.game),
        home=str(instance.home),
        resources=str(resources),
        session=session,
        env=env,
        notes=notes,
    )


def play(
    project,
    instance,
    *,
    session_path: Path | None = None,
    account: auth.Account | None = None,
    width: int | None = None,
    height: int | None = None,
    fullscreen: bool | None = None,
    world: str | None = None,
    server: str | None = None,
    extra: list[str] | None = None,
    allow_offline: bool = False,
    log=info,
) -> int:
    """Start the game and return what a launcher should report (the exit code)."""
    session_json = ""
    if account is None and session_path is None:
        try:
            account = auth.load_account(project)
        except PortError:
            account = None
    if account is not None and session_path is None:
        if account.owns or not project.policy.get("ownerGate", True):
            _maybe_refresh(project, account)
            session_json = json.dumps(account.session())
        elif project.policy.get("ownerGate", True):
            raise PortError(
                "This account doesn't own Minecraft: Java Edition, so the game is not started.",
                hint="Sign in with the account that owns the game (the owner gate is policy.ownerGate).",
            )
    if session_path is not None and not session_json:
        session = auth.read_session(session_path)
        session_json = json.dumps(session)
    if not session_json and not allow_offline:
        raise PortError(
            "no session: Horizon starts the game for a signed-in account that owns it",
            hint="Run `horizonport auth sign-in --client-id <GUID>`, pass --session FILE, or --offline to test without one.",
        )
    if not session_json:
        warn("starting without a session: online-mode servers will refuse the player")

    launch_plan = plan(
        project,
        instance,
        session="stdin",
        width=width,
        height=height,
        fullscreen=fullscreen,
        world=world,
        server=server,
        extra=extra,
    )
    temporary: Path | None = None
    argv = list(launch_plan.argv)
    if launch_plan.session == "file" and session_json:
        project.data.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix="session-", suffix=".json", dir=str(project.data))
        os.close(handle)
        temporary = Path(name)
        temporary.chmod(0o600)
        temporary.write_text(session_json, encoding="utf-8")
        index = argv.index("--session-file") + 1
        argv[index] = str(temporary)

    log(f"starting Horizon for {instance.name}")
    try:
        process = subprocess.Popen(
            argv,
            cwd=launch_plan.cwd,
            env={**os.environ, **launch_plan.env},
            stdin=subprocess.PIPE if session_json and launch_plan.session == "stdin" else subprocess.DEVNULL,
            stdout=None,
            stderr=subprocess.PIPE,
            text=True,
        )
        _, stderr = process.communicate(input=(session_json + "\n") if session_json and launch_plan.session == "stdin" else None)
        code = process.returncode
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    instance.mark_played()
    crash = crash_report(stderr or "")
    if code != 0:
        warn(f"Horizon exited {code}: {EXIT_MEANINGS.get(code, 'unknown exit code')}")
        if crash:
            warn(f"crash report: {crash}")
        elif stderr:
            warn((stderr.strip().splitlines() or [""])[-1])
    else:
        log("the player quit")
    return code


def crash_report(stderr: str) -> str | None:
    path: str | None = None
    for line in stderr.splitlines():
        if line.startswith(CRASH_LINE):
            path = line[len(CRASH_LINE) :].strip()
    return path


def explain(code: int) -> str:
    return EXIT_MEANINGS.get(code, f"exit {code}")


def _maybe_refresh(project, account: auth.Account) -> None:
    import time

    if account.expires_at and account.expires_at - time.time() > 3600:
        return
    client_id = project.config.get("auth", {}).get("clientId") if isinstance(project.config.get("auth"), dict) else None
    if not client_id:
        return
    try:
        renewed = auth.refresh(account, client_id)
        account.access_token = renewed.access_token
        account.refresh_token = renewed.refresh_token
        account.expires_at = renewed.expires_at
        auth.save_account(project, account)
    except PortError as exc:
        warn(f"could not renew the sign-in ({exc.message}); using the current token")
