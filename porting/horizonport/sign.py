"""Signed release checksums, checked without third-party packages.

Horizon publishes every build with `SHA256SUMS` and `SHA256SUMS.sig`, an
Ed25519 signature over `horizon release <tag>\\n` followed by the checksum
file's bytes (`crates/horizon-release-sign/src/lib.rs`). A port that installs a
build must verify both before unpacking it, so this module carries a small,
audited-by-test Ed25519 verifier (RFC 8032) instead of asking the developer to
pip-install one.

The public keys live in `crates/horizon-release-sign/release-keys.txt` in the
engine checkout; `--keys` overrides them, and a port that signs its own builds
can put its own key file in `port.config.json`.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from .util import PortError

# --- Ed25519 (RFC 8032), verification only ---------------------------------
_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)
_BASE_ENC = bytes.fromhex(
    "5866666666666666666666666666666666666666666666666666666666666666"
)


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


def _decode(encoded: bytes) -> tuple[int, int, int, int] | None:
    if len(encoded) != 32:
        return None
    raw = int.from_bytes(encoded, "little")
    sign = (raw >> 255) & 1
    y = raw & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _add(
    one: tuple[int, int, int, int], other: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    x1, y1, z1, t1 = one
    x2, y2, z2, t2 = other
    a = (y1 - x1) * (y2 - x2) % _P
    b = (y1 + x1) * (y2 + x2) % _P
    c = t1 * 2 * _D * t2 % _P
    d = z1 * 2 * z2 % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _double(one: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x1, y1, z1, _ = one
    a, b = x1 * x1 % _P, y1 * y1 % _P
    c = 2 * z1 * z1 % _P
    d = -a % _P
    e = (x1 + y1) * (x1 + y1) - a - b
    g = d + b
    f = g - c
    h = d - b
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _scalar_mul(scalar: int, point: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    result = (0, 1, 1, 0)
    addend = point
    while scalar:
        if scalar & 1:
            result = _add(result, addend)
        addend = _double(addend)
        scalar >>= 1
    return result


def _encode(point: tuple[int, int, int, int]) -> bytes:
    x, y, z, _ = point
    zinv = _inv(z)
    x, y = x * zinv % _P, y * zinv % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


_BASE = _decode(_BASE_ENC)
assert _BASE is not None  # the base point is fixed by RFC 8032


def ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """True when `signature` is `message`'s Ed25519 signature under `public_key`."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    key = _decode(public_key)
    r = _decode(signature[:32])
    if key is None or r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    challenge = int.from_bytes(
        hashlib.sha512(signature[:32] + public_key + message).digest(), "little"
    ) % _L
    return _encode(_scalar_mul(s, _BASE)) == _encode(_add(r, _scalar_mul(challenge, key)))


# --- Horizon's signed checksum files ---------------------------------------
SUMS = "SHA256SUMS"
SIGNATURE = "SHA256SUMS.sig"
SIGNATURE_V2 = "SHA256SUMS.v2.sig"

_EMBEDDED_KEYS = """\
# Horizon's release key (crates/horizon-release-sign/release-keys.txt).
MU4oiIQcCxkZvbwSjjXs7SySCuM6ywRQ3nGaJYZG0gw=
"""


def parse_keys(text: str) -> list[bytes]:
    keys: list[bytes] = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            raw = base64.b64decode(line, validate=True)
        except ValueError as exc:
            raise PortError(f"key line {number} is not base64: {exc}") from None
        if len(raw) != 32:
            raise PortError(f"key line {number} is not a 32-byte Ed25519 public key")
        keys.append(raw)
    return keys


def default_keys() -> list[bytes]:
    """The engine checkout's keys when there is one, else the key built in."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "crates" / "horizon-release-sign" / "release-keys.txt"
        if candidate.is_file():
            return parse_keys(candidate.read_text(encoding="utf-8"))
    return parse_keys(_EMBEDDED_KEYS)


def message(tag: str, sums: bytes) -> bytes:
    """What a signature covers: the tag line, then the checksum list."""
    return f"horizon release {tag}\n".encode("utf-8") + sums


def parse_sums(text: str) -> list[tuple[str, str]]:
    """`<sha256>  <file>` lines (sha256sum's format) as (name, hex) pairs."""
    pairs: list[tuple[str, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split(" ", 1)
        if len(parts) != 2:
            raise PortError(f"{SUMS} line {number} is not `<sha256>  <file>`: {line!r}")
        hex_digest, name = parts[0].lower(), parts[1]
        name = name[1:] if name[:1] in (" ", "*") else name
        if len(hex_digest) != 64 or any(c not in "0123456789abcdef" for c in hex_digest) or not name:
            raise PortError(f"{SUMS} line {number} is not `<sha256>  <file>`: {line!r}")
        pairs.append((name, hex_digest))
    if not pairs:
        raise PortError(f"{SUMS} lists no files")
    return pairs


def verify_sums(
    tag: str, sums: bytes, signatures: str, keys: list[bytes]
) -> list[tuple[str, str]]:
    """Check that one of `keys` signed `sums` for `tag`, and return the file list."""
    if not keys:
        raise PortError(
            "This build has no release key, so no download can be checked.",
            hint="Pass --keys PATH, or --allow-unsigned for a build you made yourself.",
        )
    signed = message(tag, sums)
    for line in signatures.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            signature = base64.b64decode(line, validate=True)
        except ValueError:
            continue
        if any(ed25519_verify(key, signed, signature) for key in keys):
            try:
                return parse_sums(sums.decode("utf-8"))
            except UnicodeDecodeError:
                raise PortError(f"{SUMS} is not text") from None
    raise PortError(
        f"{tag}'s signature does not match Horizon's release key, so nothing was installed.",
        hint="The download may have been tampered with. Report it on Discord or GitHub.",
    )


def lookup(files: list[tuple[str, str]], name: str) -> str:
    for candidate, digest in files:
        if candidate == name:
            return digest
    raise PortError(
        f"{SUMS} does not list {name}",
        hint="This release may not be built for your platform.",
    )
