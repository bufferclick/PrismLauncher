"""Microsoft sign-in: the seven steps, and the owner gate.

The launcher signs the player in, not the game. Horizon's contract is that the
launcher hands the game a *session* only for an account that owns Minecraft:
Java Edition (`docs/api/launch.md`, "The session JSON"), the same gate
`horizon-launcher` applies before every start.

The flow, in order, all over HTTPS:

    device code  ->  Microsoft token  ->  Xbox Live  ->  XSTS
                 ->  Minecraft token  ->  entitlements  ->  profile

This module implements it with `urllib`, keeps a transport seam so tests never
touch the network, and writes the session JSON with mode 0600. A shipping
launcher should keep the refresh token in the OS keychain; the file store here
is for development, CI and launchers that already encrypt their own secrets.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import net
from .util import PortError, atomic_write_text, now_utc, read_json, write_json

DEVICE_CODE = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
TOKEN = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
XBL = "https://user.auth.xboxlive.com/user/authenticate"
XSTS = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_LOGIN = "https://api.minecraftservices.com/authentication/login_with_xbox"
ENTITLEMENTS = "https://api.minecraftservices.com/entitlements/mcstore"
PROFILE = "https://api.minecraftservices.com/minecraft/profile"
SCOPE = "XboxLive.signin offline_access"

XERR = {
    "2148916233": "This Microsoft account has no Xbox profile yet. Sign in at xbox.com once.",
    "2148916235": "Xbox Live is not available in this account's country.",
    "2148916236": "This account needs adult verification (South Korea).",
    "2148916237": "This account needs adult verification (South Korea).",
    "2148916238": "This is a child account. Add it to a Microsoft family, then try again.",
}


@dataclass
class Account:
    name: str
    uuid: str
    access_token: str
    refresh_token: str = ""
    expires_at: float = 0.0
    xuid: str = ""
    owns: bool = False

    def session(self) -> dict[str, str]:
        """The JSON `horizon-client --session-stdin` reads."""
        session = {
            "name": self.name,
            "uuid": self.uuid,
            "access_token": self.access_token,
            "user_type": "msa",
        }
        if self.xuid:
            session["xuid"] = self.xuid
        return session

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "uuid": self.uuid,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expiresAt": self.expires_at,
            "xuid": self.xuid,
            "owns": self.owns,
        }

    @classmethod
    def from_json(cls, value: dict) -> "Account":
        try:
            return cls(
                name=value["name"],
                uuid=value["uuid"],
                access_token=value["access_token"],
                refresh_token=value.get("refresh_token", ""),
                expires_at=float(value.get("expiresAt", 0)),
                xuid=value.get("xuid", ""),
                owns=bool(value.get("owns", False)),
            )
        except KeyError as exc:
            raise PortError(f"the stored account is missing {exc.args[0]}") from None


class HttpTransport:
    """The real endpoints, one method each so tests can fake them all."""

    def device_code(self, client_id: str) -> dict:
        return net.post_form(DEVICE_CODE, {"client_id": client_id, "scope": SCOPE}).json()

    def poll_token(self, client_id: str, device_code: str) -> tuple[int, dict]:
        response = net.post_form(
            TOKEN,
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": client_id,
                "device_code": device_code,
            },
        )
        return response.status, response.json()

    def refresh_token(self, client_id: str, refresh_token: str) -> dict:
        return net.post_form(
            TOKEN,
            {
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
                "scope": SCOPE,
            },
        ).json()

    def xbl(self, microsoft_token: str) -> dict:
        return net.post_json(
            XBL,
            {
                "Properties": {
                    "AuthMethod": "RPS",
                    "SiteName": "user.auth.xboxlive.com",
                    "RpsTicket": f"d={microsoft_token}",
                },
                "RelyingParty": "http://auth.xboxlive.com",
                "TokenType": "JWT",
            },
            headers={"x-xbl-contract-version": "1"},
        ).json()

    def xsts(self, xbl_token: str) -> dict:
        return net.post_json(
            XSTS,
            {
                "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl_token]},
                "RelyingParty": "rp://api.minecraftservices.com/",
                "TokenType": "JWT",
            },
            headers={"x-xbl-contract-version": "1"},
        ).json()

    def minecraft(self, uhs: str, xsts_token: str) -> dict:
        return net.post_json(
            MC_LOGIN, {"identityToken": f"XBL3.0 x={uhs};{xsts_token}"}
        ).json()

    def entitlements(self, access_token: str) -> dict:
        return net.get(ENTITLEMENTS, headers={"Authorization": f"Bearer {access_token}"}).json()

    def profile(self, access_token: str) -> tuple[int, dict]:
        try:
            response = net.get(PROFILE, headers={"Authorization": f"Bearer {access_token}"})
        except PortError as exc:
            if "answered 404" in exc.message:
                return 404, {}
            raise
        return response.status, response.json()


def sign_in(
    client_id: str,
    *,
    transport: HttpTransport | None = None,
    on_code: Callable[[str, str, float], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
    max_wait: float = 900.0,
) -> Account:
    """Run the device-code flow and return an account that owns the game.

    `on_code(verification_uri, user_code, expires_in)` shows the player what to
    type; nothing else is interactive. The account's ownership is checked before
    returning, so a caller can't accidentally start a game for a non-owner.
    """
    transport = transport or HttpTransport()
    if not client_id:
        raise PortError(
            "no Microsoft client ID",
            hint=(
                "Register an Azure app (docs/microsoft-account.md) and pass its Application (client) ID. "
                "Never reuse Horizon's or another launcher's ID."
            ),
        )
    start = transport.device_code(client_id)
    device_code = start.get("device_code")
    if not isinstance(device_code, str):
        raise PortError(f"Microsoft's device-code reply is missing device_code: {start}")
    uri = str(start.get("verification_uri") or "https://www.microsoft.com/link")
    user_code = str(start.get("user_code") or "")
    if on_code:
        on_code(uri, user_code, float(start.get("expires_in", 900)))

    interval = float(start.get("interval", 5))
    deadline = clock() + min(float(start.get("expires_in", 900)), max_wait)
    tokens: dict | None = None
    while clock() < deadline:
        sleep(interval)
        status, answer = transport.poll_token(client_id, device_code)
        error = answer.get("error")
        if not error:
            tokens = answer
            break
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error == "authorization_declined":
            raise PortError("The sign-in was declined in the browser.")
        if error == "expired_token":
            raise PortError("The sign-in code expired. Try again.")
        if error == "bad_verification_code":
            raise PortError("Microsoft refused the sign-in code. Try again.")
        raise PortError(f"Microsoft refused the sign-in: {answer.get('error_description', error)}")
    if tokens is None:
        raise PortError("The sign-in timed out before it was approved in the browser.")

    xbl = transport.xbl(tokens["access_token"])
    try:
        uhs = xbl["DisplayClaims"]["xui"][0]["uhs"]
        xbl_token = xbl["Token"]
    except (KeyError, IndexError, TypeError):
        raise PortError("Xbox Live's reply is unexpected; the sign-in stopped") from None

    xsts = transport.xsts(xbl_token)
    if "XErr" in xsts:
        raise PortError(XERR.get(str(xsts["XErr"]), f"Xbox Live refused the sign-in (XErr {xsts['XErr']})."))
    xsts_token = xsts.get("Token")
    if not isinstance(xsts_token, str):
        raise PortError("Xbox Live's reply has no token; the sign-in stopped")

    mc = transport.minecraft(uhs, xsts_token)
    access = mc.get("access_token")
    if not isinstance(access, str):
        raise PortError(
            "Minecraft refused the sign-in: "
            + str(mc.get("errorMessage") or "This app is not approved by Mojang yet (see docs/microsoft-account.md)."),
        )
    expires_in = float(mc.get("expires_in", 86400))

    if not ownership(transport, access):
        raise PortError(
            "This account doesn't own Minecraft: Java Edition.",
            hint="Sign in with the account that bought the game (Game Pass counts).",
        )
    name, uuid, xuid = profile(transport, access)
    return Account(
        name=name,
        uuid=uuid,
        access_token=access,
        refresh_token=str(tokens.get("refresh_token", "")),
        expires_at=clock() + expires_in,
        xuid=xuid,
        owns=True,
    )


def ownership(transport: HttpTransport, access_token: str) -> bool:
    items = transport.entitlements(access_token).get("items", [])
    names = {str(item.get("name", "")) for item in items if isinstance(item, dict)}
    return bool(names & {"game_minecraft", "product_minecraft"})


def profile(transport: HttpTransport, access_token: str) -> tuple[str, str, str]:
    status, payload = transport.profile(access_token)
    if status == 404 or not payload.get("id"):
        raise PortError(
            "This account owns the game but has no Minecraft profile yet.",
            hint="Create one at minecraft.net, then sign in again.",
        )
    return str(payload.get("name", "")), str(payload["id"]), str(payload.get("xuid", ""))


def refresh(account: Account, client_id: str, transport: HttpTransport | None = None) -> Account:
    """Renew the Minecraft token from the stored Microsoft refresh token."""
    transport = transport or HttpTransport()
    if not account.refresh_token:
        raise PortError("There is no refresh token for this account; sign in again.")
    tokens = transport.refresh_token(client_id, account.refresh_token)
    if "error" in tokens:
        raise PortError("Microsoft refused to renew the sign-in; sign in again.")
    xbl = transport.xbl(tokens["access_token"])
    uhs = xbl["DisplayClaims"]["xui"][0]["uhs"]
    xsts = transport.xsts(xbl["Token"])
    if "XErr" in xsts:
        raise PortError(XERR.get(str(xsts["XErr"]), "Xbox Live refused the renewal."))
    mc = transport.minecraft(uhs, xsts["Token"])
    access = mc.get("access_token")
    if not isinstance(access, str):
        raise PortError("Minecraft refused the renewal; sign in again.")
    renewed = Account(
        name=account.name,
        uuid=account.uuid,
        access_token=access,
        refresh_token=str(tokens.get("refresh_token", account.refresh_token)),
        expires_at=time.time() + float(mc.get("expires_in", 86400)),
        xuid=account.xuid,
        owns=account.owns,
    )
    if not ownership(transport, access):
        renewed.owns = False
    return renewed


# ---------------------------------------------------------------------------
# Sessions on disk
# ---------------------------------------------------------------------------
def write_session(path: Path, account: Account) -> Path:
    """Write the session JSON, readable by the player's user only."""
    atomic_write_text(path, json.dumps(account.session()) + "\n", mode=0o600)
    return path


def read_session(path: Path) -> dict:
    value = read_json(path)
    for key in ("name", "uuid", "access_token"):
        if not value.get(key):
            raise PortError(f"{path} is not a session: it has no {key}")
    if value.get("user_type") not in (None, "msa"):
        raise PortError(f"{path}: user_type must be \"msa\"")
    return value


def save_account(project, account: Account) -> Path:
    """Keep the account's secrets in the port's data folder (mode 0600)."""
    project.secrets.mkdir(parents=True, exist_ok=True)
    path = project.secrets / f"{account.uuid}.json"
    atomic_write_text(path, json.dumps(account.to_json(), indent=2) + "\n", mode=0o600)
    index = project.data / "accounts.json"
    accounts = []
    if index.exists():
        accounts = [item for item in read_json(index).get("accounts", []) if item.get("uuid") != account.uuid]
    accounts.append(
        {
            "name": account.name,
            "uuid": account.uuid,
            "owns": account.owns,
            "expiresAt": account.expires_at,
            "signedInAt": now_utc(),
        }
    )
    write_json(index, {"accounts": accounts})
    return path


def load_account(project, who: str | None = None) -> Account:
    who = who or os.environ.get("HORIZONPORT_ACCOUNT")
    candidates = sorted(project.secrets.glob("*.json")) if project.secrets.is_dir() else []
    if not candidates:
        raise PortError(
            "no signed-in account",
            hint="Run `horizonport auth sign-in --client-id <GUID>` first, or pass --session.",
        )
    path = candidates[0]
    if who:
        match = [p for p in candidates if p.stem == who.replace("-", "").lower() or p.stem == who]
        if not match:
            raise PortError(f"no signed-in account matches {who!r}")
        path = match[0]
    return Account.from_json(read_json(path))
