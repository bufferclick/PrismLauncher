# Sign-in, the owner gate, and sessions

Horizon plays with the player's own Microsoft account, and only with one that **owns Minecraft: Java
Edition**. That is the same rule the official launcher and `horizon-launcher` apply. This page is the
launcher developer's version of [`docs/microsoft-account.md`](../docs/microsoft-account.md): what to
register, what to call, what to store, and what to say when it fails.

## What you must register (once, ever)

1. **Azure app registration** — <https://portal.azure.com> → Microsoft Entra ID → App registrations → New.
   * Name: your launcher's name. It is what the player sees on the Microsoft consent page.
   * Supported account types: **Personal Microsoft accounts only**. Minecraft accounts are consumer accounts.
   * Redirect URI: none (device-code flow). If the form insists, use a "Mobile and desktop applications"
     redirect of `https://login.microsoftonline.com/common/oauth2/nativeclient`.
   * Authentication → Advanced → **Allow public client flows: Yes** (this is what enables device code).
     There is no client secret: a launcher is a public client.
   * API permissions: none to add. Request `XboxLive.signin offline_access` at sign-in.
   * Copy the **Application (client) ID** into `port.config.json` → `auth.clientId`.
2. **Mojang's Minecraft app-ID review** — a brand-new Azure app is refused by
   `api.minecraftservices.com/authentication/login_with_xbox` (HTTP 403, "Invalid app registration") until
   Mojang approves it. Apply at <https://aka.ms/mce-reviewappid> with the client ID, the launcher's name and
   URL, and a sentence about what it does. Days to weeks. Until then, sign-in fails at the Minecraft step —
   and your UI must say exactly that, not "wrong password".
3. **Never** use another launcher's client ID (including Horizon's). It is both a security and a policy
   problem: the consent screen would name someone else's app.

## The flow, step by step

All HTTPS + JSON except the two OAuth calls, which are form-encoded.

| # | Call | Body | You get |
| --- | --- | --- | --- |
| 1 | `POST https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode` | `client_id`, `scope=XboxLive.signin offline_access` | `device_code`, `user_code`, `verification_uri`, `interval`, `expires_in` |
| 2 | `POST …/consumers/oauth2/v2.0/token` every `interval` s | `grant_type=urn:ietf:params:oauth:grant-type:device_code`, `client_id`, `device_code` | after approval: Microsoft `access_token` + `refresh_token` |
| 3 | `POST https://user.auth.xboxlive.com/user/authenticate` | `{Properties:{AuthMethod:"RPS",SiteName:"user.auth.xboxlive.com",RpsTicket:"d=<MS token>"},RelyingParty:"http://auth.xboxlive.com",TokenType:"JWT"}` | XBL `Token`, and `DisplayClaims.xui[0].uhs` |
| 4 | `POST https://xsts.auth.xboxlive.com/xsts/authorize` | `{Properties:{SandboxId:"RETAIL",UserTokens:["<XBL token>"]},RelyingParty:"rp://api.minecraftservices.com/",TokenType:"JWT"}` | XSTS `Token` (or `XErr`) |
| 5 | `POST https://api.minecraftservices.com/authentication/login_with_xbox` | `{identityToken:"XBL3.0 x=<uhs>;<XSTS token>"}` | Minecraft `access_token` (24 h), `expires_in` |
| 6 | `GET https://api.minecraftservices.com/entitlements/mcstore` | `Authorization: Bearer <MC token>` | `items[]`; ownership means `game_minecraft` or `product_minecraft` |
| 7 | `GET https://api.minecraftservices.com/minecraft/profile` | same | `id` (UUID), `name`, skins, capes, `xuid` |

Poll statuses: `authorization_pending` → keep waiting; `slow_down` → add 5 s to the interval;
`authorization_declined` → the player said no; `expired_token` → start again; `bad_verification_code` → start
again. Show the code with a copy button and open the browser at `verification_uri`
(`https://www.microsoft.com/link`) — the player types the code there.

`XErr` values and the messages to show:

| XErr | Message |
| --- | --- |
| 2148916233 | "This Microsoft account has no Xbox profile yet. Sign in at xbox.com once." |
| 2148916235 | "Xbox Live is not available in this account's country." |
| 2148916236 / 2148916237 | "This account needs adult verification (South Korea)." |
| 2148916238 | "This is a child account. Add it to a Microsoft family, then try again." |

Anything else: name the XErr number and link to support; do not guess.

### One quirk worth designing for

The device-code page uses whatever Microsoft account the browser is already signed in to, and the flow has no
account picker. `horizon-launcher` solves it with an "Open in private window" button (a private window has no
session). Do the same, or offer "copy link" plus the hint; do not silently sign the wrong account in.

## The session JSON

What the game gets, and the only three required fields:

```json
{"name": "Alex", "uuid": "069a79f444e94726a5befca90e38aaf5", "access_token": "…", "user_type": "msa", "xuid": "…"}
```

* `--session-stdin`: write it to the child's stdin and close stdin. Preferred: nothing touches the disk.
* `--session-file PATH`: a file the game reads once and deletes. Mode **0600** on Unix; a file older than two
  minutes is refused.
* A session the game can't read is reported on stderr (`Horizon: not signed in: …`); the game still starts,
  and online-mode servers refuse the player.

Never pass a token as a command-line argument: `/proc/<pid>/cmdline`, Task Manager and the window title are
all world-readable.

## What to store, and where

| Secret | Lifetime | Store |
| --- | --- | --- |
| Microsoft refresh token | until revoked | OS keychain (Keychain / Credential Manager / Secret Service) |
| Minecraft access token | 24 h | memory, and only long enough to write the session |
| Last ownership answer | last check | with the account, so being offline doesn't lock out a previous owner |
| Profile (name, UUID, skin) | long | plain storage, no secret |

`horizonport` itself writes `secrets/<uuid>.json` (mode 0600) and `accounts.json` (no tokens) because a
command-line tool cannot assume a keychain. A shipping launcher should use the keychain; if it can't, encrypt
the secrets file and say so in its privacy page. `docs/microsoft-account.md` documents the engine's own
behaviour, including Windows' 2560-byte credential limit.

## The owner gate

* **Play asks every time.** Refresh the token if it expires within the hour, then `entitlements` and
  `profile`. No owner → no start.
* **Offline stands.** A failed *network* call is not a "doesn't own": the last answer stands and the game
  starts without a session (single player works; online servers refuse). A fresh "doesn't own" blocks at once.
* **The playing account must own it.** Selecting account B because account A owns the game is not allowed.
* **No bypass.** No `--offline` in the shipped launcher, no hidden setting, no developer flag. The toolkit's
  `play --offline` exists for testing **your** adapter and prints a warning; do not wire it to a button.

Say why the gate exists, once, in the UI: "Horizon contains no Minecraft files. Playing it with your own
account is what makes that legal, and it's what lets you join online servers with your own name and skin."

## Multi-account and clearing

* Several accounts may be signed in; one is selected. `accounts.json` lists names and UUIDs; each secret is
  its own file.
* "Sign out" deletes that account's secret file (or keychain item) and its ownership answer. It does not
  touch worlds, the store or mods.
* Switching accounts never re-downloads resources: they belong to the build and game version, not the player.

## Testing sign-in without an account

* Unit-test with a fake transport: `tests/test_horizonport_launch.py` has one (`FakeTransport`) covering
  pending polls, non-owners, child accounts and the session file's mode.
* End-to-end needs a real owner. Do not add a test hook to production code to avoid that; a test that fakes
  the gate proves nothing about the gate.
* If your CI has no owner, test the *refusal*: no session → Play refuses, with the sign-in screen.

## The error copy that saves support tickets

| Situation | Say this |
| --- | --- |
| No client ID | "This build of <launcher> has no Microsoft sign-in configured." |
| App not approved | "Microsoft accepted the sign-in, but Mojang has not approved this app yet. It is pending." |
| No ownership | "This Microsoft account doesn't own Minecraft: Java Edition. Play needs the account that bought it (Game Pass counts)." |
| No profile | "This account owns the game but has no Minecraft profile yet. Create one at minecraft.net." |
| Declined | "The sign-in was declined in the browser." |
| Expired code | "That code expired. Here's a new one." |
| Offline | "You're offline. Playing single player; online servers need a connection." |

Every one of these should have a "copy details" button and no token in the details.
