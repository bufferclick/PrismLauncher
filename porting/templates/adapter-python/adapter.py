"""A launcher adapter in Python: every port action is one `horizonport` command.

This is the smallest useful adapter, and the template for a launcher that is
itself written in Python (or that wants to call the toolkit without a shell
command in between). It keeps the launcher on the CLI, so there is one
implementation of the security-sensitive parts: signature checks, archive
unpacking, preparation, digests.

A port's three calls are: `sign in`, `add an instance`, `play`. The rest of this
file is those three, plus the checks that tell a UI what to show.

Usage from a launcher:

    from adapter import HorizonPort

    kit = HorizonPort(project="~/MyLauncher")
    kit.add_instance("Work")                  # reuses the prepared tree
    code = kit.play("Work", on_line=print)    # 0 quit, 1 error, 2 our bug, 101 panic
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class ToolError(RuntimeError):
    """A toolkit command refused or failed. `code` is the process exit code."""

    def __init__(self, message: str, *, code: int = 1, hint: str = "", stderr: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint
        self.stderr = stderr

    def __str__(self) -> str:  # a UI can show this as it is
        return f"{self.message}\n{self.hint}" if self.hint else self.message


def toolkit_root() -> Path:
    """The folder that contains `porting/horizonport`, found once and cached."""
    configured = os.environ.get("HORIZONPORT")
    if configured:
        return Path(configured).expanduser().resolve()
    folder = Path(__file__).resolve().parent
    for candidate in (folder, *folder.parents):
        if (candidate / "porting" / "horizonport").is_dir():
            return candidate
    return folder.parent.parent


@dataclass(frozen=True)
class Instance:
    name: str
    build: str
    prepared: str
    game_dir: str
    home: str

    @classmethod
    def from_json(cls, item: dict) -> "Instance":
        return cls(
            name=item.get("name", ""),
            build=item.get("build", ""),
            prepared=item.get("prepared", ""),
            game_dir=item.get("gameDir", ""),
            home=item.get("home", ""),
        )


class HorizonPort:
    """One port project, driven through the toolkit's JSON interface."""

    def __init__(
        self,
        project: str | os.PathLike[str],
        *,
        python: str | None = None,
        root: str | os.PathLike[str] | None = None,
        on_log=None,
    ) -> None:
        self.project = Path(project).expanduser().resolve()
        self.python = python or ("python" if os.name == "nt" else "python3")
        self.root = Path(root).expanduser().resolve() if root else toolkit_root()
        self.on_log = on_log or (lambda line: None)

    # -- the CLI ----------------------------------------------------------

    @property
    def config_file(self) -> Path:
        return self.project / "port.config.json"

    def config(self) -> dict:
        if not self.config_file.is_file():
            raise ToolError(
                f"no port.config.json in {self.project}",
                code=2,
                hint="Run `horizonport init` first, or point the adapter at the project folder.",
            )
        return json.loads(self.config_file.read_text(encoding="utf-8"))

    def run(self, *args: str, timeout: float | None = None, allow_codes: tuple[int, ...] = (0,)) -> dict:
        """Run one toolkit command and return its `--json` object."""
        argv = [
            self.python, "-m", "porting.horizonport",
            "--json", "--project", str(self.project), *args,
        ]
        try:
            completed = subprocess.run(
                argv,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except OSError as exc:
            raise ToolError(f"could not run the toolkit: {exc}", hint="Is python3 on PATH?") from exc
        except subprocess.TimeoutExpired as exc:
            raise ToolError(f"`horizonport {' '.join(args)}` took too long", code=1) from exc
        for line in (completed.stdout or "").splitlines():
            if line.strip():
                self.on_log(line)
        payload: dict = {}
        for line in reversed((completed.stdout or "").splitlines()):
            if line.strip().startswith("{"):
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                break
        if completed.returncode not in allow_codes or payload.get("error"):
            message = (
                payload.get("error")
                or (completed.stderr or "").strip().splitlines()[-1:] or ["the toolkit failed"]
            )
            if isinstance(message, list):
                message = message[0] if message else "the toolkit failed"
            raise ToolError(message, code=completed.returncode, hint=payload.get("hint", ""), stderr=completed.stderr)
        return payload

    # -- the three calls a launcher makes ---------------------------------

    def doctor(self, full: bool = False) -> dict:
        """What this machine can do. Show the `FAIL` rows; explain the `WARN` ones."""
        # doctor exits 1 when a check fails; the checks themselves are the answer.
        return self.run("doctor", *(["--full"] if full else []), allow_codes=(0, 1))

    def fetch(self, *, tag: str | None = None, archive: str | None = None, allow_unsigned: bool = False) -> dict:
        """Install a signed build. Refuses to install anything it cannot verify."""
        args = ["fetch"]
        if tag:
            args += ["--tag", tag]
        if archive:
            args += ["--archive", archive]
        if allow_unsigned:  # only for a build this launcher compiled itself
            args += ["--allow-unsigned"]
        return self.run(*args)

    def prepare(self, *, build: str | None = None, download: bool = False, from_install: str | None = None,
                session: str | None = None, server_jar: str | None = None) -> dict:
        """Prepare resources once per build. Minutes; show progress, allow cancel."""
        args = ["prepare"]
        if build:
            args += ["--build", build]
        if download:
            args += ["--download"]
        if from_install:
            args += ["--from-install", from_install]
        if session:
            args += ["--session", session]
        if server_jar:
            args += ["--server-jar", server_jar]
        return self.run(*args)

    def setup(self, *, tag: str | None = None, download: bool = False, from_install: str | None = None,
              session: str | None = None) -> dict:
        """The "add Horizon" action: build, then resources, reusing everything already there."""
        build = self.fetch(tag=tag)
        resources = self.prepare(build=tag, download=download, from_install=from_install, session=session)
        return {"build": build, "resources": resources}

    def add_instance(self, name: str, *, build: str | None = None, no_prepare: bool = False) -> Instance:
        """Create an instance. Reuses the prepared tree: this is fast after the first one."""
        args = ["instance", "new", name]
        if build:
            args += ["--build", build]
        if no_prepare:
            args += ["--no-prepare"]
        return Instance.from_json(self.run(*args).get("instance", {}))

    def instances(self) -> list[dict]:
        return self.run("instance", "list").get("instances", [])

    def plan(self, instance: str, **options) -> dict:
        """The exact argv the game would get, without starting it."""
        args = ["play", instance, "--dry-run"]
        if "width" in options:
            args += ["--width", str(options["width"])]
        if "height" in options:
            args += ["--height", str(options["height"])]
        if options.get("fullscreen"):
            args += ["--fullscreen"]
        if options.get("world"):
            args += ["--world", options["world"]]
        if options.get("server"):
            args += ["--server", options["server"]]
        return self.run(*args)

    def play(self, instance: str, *, session: str | None = None, offline: bool = False,
             on_line=None, **options) -> int:
        """Start the game and wait. Returns the game's exit code, unchanged."""
        args = ["play", instance]
        if session:
            args += ["--session", session]
        if offline:
            args += ["--offline"]
        for key in ("width", "height"):
            if key in options:
                args += [f"--{key}", str(options[key])]
        if options.get("fullscreen"):
            args += ["--fullscreen"]
        if options.get("world"):
            args += ["--world", options["world"]]
        if options.get("server"):
            args += ["--server", options["server"]]
        # Here the launcher wants the process, not JSON: stream the output.
        argv = [self.python, "-m", "porting.horizonport", "--project", str(self.project), *args]
        report = on_line or self.on_log
        process = subprocess.Popen(argv, cwd=str(self.root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert process.stdout is not None
        for line in process.stdout:
            report(line.rstrip("\n"))
        return process.wait()

    def check(self, full: bool = False, support: str | None = None) -> dict:
        """The seven gates. `support` writes a token-free folder for a bug report."""
        args = ["check"]
        if full:
            args += ["--full"]
        if support:
            args += ["--support", support]
        return self.run(*args)


EXIT_MEANINGS = {
    0: "The player quit.",
    1: "Horizon stopped on an error. Show the crash report path from the last stderr line.",
    2: "The launcher asked for something the build does not accept: our bug, not a crash.",
    101: "Horizon panicked. Show the crash report path from the last stderr line.",
}


def explain(code: int) -> str:
    return EXIT_MEANINGS.get(code, f"Horizon exited with {code}.")


if __name__ == "__main__":  # a smoke test: `python3 adapter.py <project> <instance>`
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    kit = HorizonPort(sys.argv[1], on_log=print)
    print(json.dumps(kit.plan(sys.argv[2]), indent=2))
    raise SystemExit(kit.play(sys.argv[2], on_line=print))
