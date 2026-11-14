"""Small, dependency-free helpers shared by the HorizonPort commands.

Everything here is deliberately boring: JSON with stable ordering, SHA-256,
atomic writes, hardlinks with a copy fallback, and process plumbing. No
third-party packages, because a launcher developer must be able to run the
toolkit on a bare `python3`.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Iterator

SCHEMA_STAMP = "horizonport/1"
CHUNK = 1024 * 1024


class PortError(Exception):
    """A problem the player or the agent can act on. Printed without a traceback."""

    def __init__(self, message: str, *, code: int = 1, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _paint(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def info(message: str) -> None:
    print(message, flush=True)


def ok(message: str) -> None:
    print(f"{_paint('32', 'ok')} {message}", flush=True)


def warn(message: str) -> None:
    print(f"{_paint('33', 'warning')} {message}", file=sys.stderr, flush=True)


def error(message: str) -> None:
    print(f"{_paint('31', 'error')} {message}", file=sys.stderr, flush=True)


def step(number: int | str, message: str) -> None:
    print(f"{_paint('36', f'[{number}]')} {message}", flush=True)


def table(rows: Iterable[tuple[str, str, str]], headers: tuple[str, str, str] | None = None) -> None:
    """Three-column aligned output: status, subject, detail."""
    rows = list(rows)
    widths = [
        max([len(headers[i]) if headers else 0] + [len(r[i]) for r in rows]) for i in range(3)
    ]
    if headers:
        print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip())
        print("  ".join("-" * widths[i] for i in range(3)))
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())


# ---------------------------------------------------------------------------
# JSON, digests and files
# ---------------------------------------------------------------------------
def read_json(path: Path) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise PortError(f"{path} does not exist", hint=_missing_json_hint(path)) from None
    except json.JSONDecodeError as exc:
        raise PortError(f"{path} is not valid JSON: {exc}") from None


def dumps(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def write_json(path: Path, value: Any, *, mode: int | None = None) -> None:
    atomic_write_text(path, dumps(value), mode=mode)


def atomic_write_text(path: Path, text: str, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise PortError(f"{path} does not exist") from None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_files(root: Path) -> Iterator[Path]:
    """Every regular file under `root`, in a stable order, skips symlinks."""
    for base, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(files):
            path = Path(base, name)
            if path.is_symlink() or not path.is_file():
                continue
            yield path


def digest_tree(root: Path) -> tuple[str, int, int]:
    """A content digest for a folder: (hex digest, file count, bytes).

    The digest answers "is this prepared folder the same one I verified
    before?" without trusting timestamps. It hashes `<relpath>\\0<sha256>\\n`
    for every file in sorted order, so adding, removing or editing any file
    changes it.
    """
    digest = hashlib.sha256()
    files = 0
    total = 0
    for path in tree_files(root):
        rel = path.relative_to(root).as_posix()
        size = path.stat().st_size
        digest.update(f"{rel}\0{sha256_file(path)}\n".encode("utf-8"))
        files += 1
        total += size
    return digest.hexdigest(), files, total


def link_or_copy(src: Path, dst: Path) -> str:
    """Put `src` at `dst` cheaply. Returns 'link', 'copy' or 'skip'."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        try:
            if dst.stat().st_size == src.stat().st_size and sha256_file(dst) == sha256_file(src):
                return "skip"
        except OSError:
            pass
        dst.unlink()
    try:
        os.link(src, dst)
        return "link"
    except (OSError, NotImplementedError, AttributeError):
        shutil.copy2(src, dst)
        return "copy"


def copy_tree(src: Path, dst: Path) -> int:
    """Copy a folder, reusing existing identical files. Returns files touched."""
    touched = 0
    for path in tree_files(src):
        rel = path.relative_to(src)
        if link_or_copy(path, dst / rel) != "skip":
            touched += 1
    return touched


def remove_tree(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in tree_files(path))


def human_bytes(size: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(size) < 1024 or unit == "TiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------
def which(name: str) -> str | None:
    return shutil.which(name)


def run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = None,
    capture: bool = True,
) -> subprocess.CompletedProcess:
    """Run a child process with readable failure messages."""
    try:
        return subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            env=env,
            timeout=timeout,
            check=False,
            text=True,
            capture_output=capture,
        )
    except FileNotFoundError:
        raise PortError(f"{argv[0]} was not found", hint="Run `horizonport doctor` to see what is missing.") from None
    except PermissionError:
        raise PortError(f"{argv[0]} is not executable") from None
    except OSError as exc:
        raise PortError(f"could not run {argv[0]}: {exc.strerror or exc}") from None
    except subprocess.TimeoutExpired:
        raise PortError(f"{argv[0]} took longer than {timeout:.0f}s and was stopped") from None


def program_name(base: str) -> str:
    return base + (".exe" if os.name == "nt" else "")


def platform_archive(arch: str | None = None, system: str | None = None) -> tuple[str, str]:
    """The Horizon release archive for this platform: (file name, archive kind)."""
    system = (system or sys.platform).lower()
    arch = (arch or platform.machine()).lower()
    if system.startswith("win"):
        return ("horizon-windows-arm64.zip" if arch in ("arm64", "aarch64") else "horizon-windows-x64.zip", "zip")
    if system == "darwin" or system.startswith("mac"):
        return ("horizon-macos-arm64.zip" if arch in ("arm64", "aarch64") else "horizon-macos-x64.zip", "zip")
    return ("horizon-linux-x86_64.tar.gz", "tar.gz")


def default_data_home() -> Path:
    """Where a port keeps its data when the config says nothing."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "HorizonPort"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "HorizonPort"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "horizonport"


def _missing_json_hint(path: Path) -> str:
    return (
        f"Run `horizonport init {path.parent if path.name.endswith('.json') else path}` first."
    )
