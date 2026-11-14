/**
 * Microsoft sign-in for a Node launcher: the device-code flow, end to end.
 *
 *   1. POST devicecode      -> a code the player types at microsoft.com/link
 *   2. poll token           -> Microsoft access + refresh token
 *   3. POST Xbox Live       -> XBL token and user hash (uhs)
 *   4. POST XSTS            -> the token Minecraft accepts
 *   5. POST login_with_xbox -> the Minecraft access token (24 h)
 *   6. GET  entitlements    -> does this account own the game?
 *   7. GET  profile         -> name, UUID, skins
 *
 * The result is the session JSON `horizon-client --session-stdin` reads. This
 * file is the porting template: a shipping launcher keeps the refresh token in
 * the OS keychain and never writes the access token anywhere but the game's
 * stdin or a 0600 file it deletes.
 *
 * Node 18+ (built-in fetch). No dependencies.
 */

import { chmodSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const DEVICE_CODE = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode";
const TOKEN = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token";
const XBL = "https://user.auth.xboxlive.com/user/authenticate";
const XSTS = "https://xsts.auth.xboxlive.com/xsts/authorize";
const MC_LOGIN = "https://api.minecraftservices.com/authentication/login_with_xbox";
const ENTITLEMENTS = "https://api.minecraftservices.com/entitlements/mcstore";
const PROFILE = "https://api.minecraftservices.com/minecraft/profile";
const SCOPE = "XboxLive.signin offline_access";

const XERR = {
  2148916233: "This Microsoft account has no Xbox profile yet. Sign in at xbox.com once.",
  2148916235: "Xbox Live is not available in this account's country.",
  2148916236: "This account needs adult verification (South Korea).",
  2148916237: "This account needs adult verification (South Korea).",
  2148916238: "This is a child account. Add it to a Microsoft family, then try again.",
};

export class SignInError extends Error {
  constructor(message, hint = "") {
    super(message);
    this.name = "SignInError";
    this.hint = hint;
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function json(response, what) {
  const text = await response.text();
  let body;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    throw new SignInError(`${what} answered something that is not JSON`);
  }
  if (!response.ok) {
    const detail = body.error_description ?? body.error ?? body.errorMessage ?? text.slice(0, 200);
    throw new SignInError(`${what} failed (${response.status}): ${detail}`);
  }
  return body;
}

const form = (fields) => ({
  method: "POST",
  headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
  body: new URLSearchParams(fields).toString(),
});

const postJson = (body) => ({
  method: "POST",
  headers: { "Content-Type": "application/json", Accept: "application/json" },
  body: JSON.stringify(body),
});

/**
 * @param {object} options
 * @param {string} options.clientId  your Azure app's Application (client) ID
 * @param {(code: {uri: string, code: string, expiresIn: number}) => void} [options.onCode]
 * @returns {Promise<{name: string, uuid: string, access_token: string, user_type: "msa", xuid?: string}>}
 */
export async function deviceCodeSignIn({ clientId, onCode, maxWaitMs = 900_000, fetchImpl = fetch } = {}) {
  if (!clientId) {
    throw new SignInError(
      "no Microsoft client ID",
      "Register an Azure app (porting/auth.md) and pass its Application (client) ID. Never reuse another launcher's.",
    );
  }
  const start = await json(
    await fetchImpl(DEVICE_CODE, form({ client_id: clientId, scope: SCOPE })),
    "Microsoft's device-code endpoint",
  );
  onCode?.({ uri: start.verification_uri, code: start.user_code, expiresIn: start.expires_in });

  let interval = (start.interval ?? 5) * 1000;
  const deadline = Date.now() + Math.min(start.expires_in * 1000, maxWaitMs);
  let tokens;
  while (!tokens) {
    if (Date.now() > deadline) throw new SignInError("The sign-in timed out before it was approved.");
    await sleep(interval);
    const response = await fetchImpl(
      TOKEN,
      form({
        grant_type: "urn:ietf:params:oauth:grant-type:device_code",
        client_id: clientId,
        device_code: start.device_code,
      }),
    );
    const body = await response.json();
    if (!body.error) {
      tokens = body;
      break;
    }
    if (body.error === "authorization_pending") continue;
    if (body.error === "slow_down") {
      interval += 5000;
      continue;
    }
    if (body.error === "authorization_declined") throw new SignInError("The sign-in was declined in the browser.");
    if (body.error === "expired_token") throw new SignInError("The sign-in code expired. Try again.");
    throw new SignInError(`Microsoft refused the sign-in: ${body.error_description ?? body.error}`);
  }

  const xbl = await json(
    await fetchImpl(
      XBL,
      postJson({
        Properties: {
          AuthMethod: "RPS",
          SiteName: "user.auth.xboxlive.com",
          RpsTicket: `d=${tokens.access_token}`,
        },
        RelyingParty: "http://auth.xboxlive.com",
        TokenType: "JWT",
      }),
    ),
    "Xbox Live",
  );
  const uhs = xbl.DisplayClaims?.xui?.[0]?.uhs;
  if (!uhs) throw new SignInError("Xbox Live's reply has no user hash.");

  const xsts = await json(
    await fetchImpl(
      XSTS,
      postJson({
        Properties: { SandboxId: "RETAIL", UserTokens: [xbl.Token] },
        RelyingParty: "rp://api.minecraftservices.com/",
        TokenType: "JWT",
      }),
    ),
    "Xbox Live's security token service",
  );
  if (xsts.XErr) throw new SignInError(XERR[xsts.XErr] ?? `Xbox Live refused the sign-in (XErr ${xsts.XErr}).`);

  const mc = await json(
    await fetchImpl(MC_LOGIN, postJson({ identityToken: `XBL3.0 x=${uhs};${xsts.Token}` })),
    "Minecraft's login",
  );
  const access = mc.access_token;
  if (!access) {
    throw new SignInError(
      "Minecraft refused the sign-in",
      "A new Azure app is refused until Mojang approves it (aka.ms/mce-reviewappid).",
    );
  }

  const entitlements = await json(
    await fetchImpl(ENTITLEMENTS, { headers: { Authorization: `Bearer ${access}` } }),
    "Minecraft's entitlements",
  );
  const owns = (entitlements.items ?? []).some((item) =>
    ["game_minecraft", "product_minecraft"].includes(item.name),
  );
  if (!owns) {
    throw new SignInError(
      "This account doesn't own Minecraft: Java Edition.",
      "Sign in with the account that bought the game (Game Pass counts).",
    );
  }

  const profileResponse = await fetchImpl(PROFILE, { headers: { Authorization: `Bearer ${access}` } });
  if (profileResponse.status === 404) {
    throw new SignInError(
      "This account owns the game but has no Minecraft profile yet.",
      "Create one at minecraft.net, then sign in again.",
    );
  }
  const profile = await json(profileResponse, "Minecraft's profile");
  const session = {
    name: profile.name,
    uuid: profile.id,
    access_token: access,
    user_type: "msa",
  };
  if (profile.xuid) session.xuid = profile.xuid;
  return session;
}

/** Write the session JSON the game reads, readable by the player's user only. */
export function writeSession(file, session) {
  const target = path.resolve(file);
  mkdirSync(path.dirname(target), { recursive: true });
  writeFileSync(target, JSON.stringify(session) + "\n", { mode: 0o600 });
  chmodSync(target, 0o600);
  return target;
}

export function readSession(file) {
  const session = JSON.parse(readFileSync(file, "utf8"));
  for (const key of ["name", "uuid", "access_token"]) {
    if (!session[key]) throw new SignInError(`${file} is not a session: it has no ${key}`);
  }
  return session;
}

/**
 * Renew a session from a stored refresh token (production: keep it in the
 * keychain). Returns a fresh session; call `writeSession` after it.
 */
export async function refreshSession({ clientId, refreshToken, fetchImpl = fetch }) {
  const tokens = await json(
    await fetchImpl(TOKEN, form({ grant_type: "refresh_token", client_id: clientId, refresh_token: refreshToken, scope: SCOPE })),
    "Microsoft's token endpoint",
  );
  const xbl = await json(
    await fetchImpl(
      XBL,
      postJson({
        Properties: { AuthMethod: "RPS", SiteName: "user.auth.xboxlive.com", RpsTicket: `d=${tokens.access_token}` },
        RelyingParty: "http://auth.xboxlive.com",
        TokenType: "JWT",
      }),
    ),
    "Xbox Live",
  );
  const uhs = xbl.DisplayClaims.xui[0].uhs;
  const xsts = await json(
    await fetchImpl(
      XSTS,
      postJson({
        Properties: { SandboxId: "RETAIL", UserTokens: [xbl.Token] },
        RelyingParty: "rp://api.minecraftservices.com/",
        TokenType: "JWT",
      }),
    ),
    "Xbox Live's security token service",
  );
  if (xsts.XErr) throw new SignInError(XERR[xsts.XErr] ?? `Xbox Live refused the renewal (XErr ${xsts.XErr}).`);
  const mc = await json(
    await fetchImpl(MC_LOGIN, postJson({ identityToken: `XBL3.0 x=${uhs};${xsts.Token}` })),
    "Minecraft's login",
  );
  const profile = await json(
    await fetchImpl(PROFILE, { headers: { Authorization: `Bearer ${mc.access_token}` } }),
    "Minecraft's profile",
  );
  const session = { name: profile.name, uuid: profile.id, access_token: mc.access_token, user_type: "msa" };
  if (profile.xuid) session.xuid = profile.xuid;
  return { session, refreshToken: tokens.refresh_token ?? refreshToken };
}
