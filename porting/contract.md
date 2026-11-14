# The HorizonPort contract, version 1

What a launcher gives HorizonPort, what HorizonPort gives the launcher, and what both promise the player.
Everything here is either checked by `horizonport check` or by a unit test; a change that breaks a row is a
contract change and needs the next contract version.

## Who does what

| Job | Launcher | HorizonPort | The engine |
| --- | --- | --- | --- |
| Microsoft sign-in (device code, XBL, XSTS, Minecraft token) | owns the UI, may use `auth.py` | implements the flow | — |
| Ownership check ("does this account own the game?") | shows the answer | asks Minecraft services | — |
| Downloading Mojang's game files | asks for it | does it, once, checked file by file | never |
| Downloading a Horizon build | asks for a build | verifies the signature, unpacks, records | publishes it |
| Preparing resources | shows progress, offers cancel | runs `horizon-prepare` once per build | exports from the player's files |
| Instance folders | owns its database, reads `instance.json` | creates the layout | writes worlds into `--game-dir` |
| Starting the game | spawns, hands the session over, reports the exit | validates the command (`--dry-run`) | the Launch API |
| Content mods | browses, installs, toggles | builds, validates, places files | loads `.hmod` from `horizon-mods/` |
| Telemetry | asks the player | keeps the answer off | obeys consent |

The line that matters: **Mojang's content and the player's session never leave the player's machine**, and
**the launcher never re-implements signature checks or preparation**.

## The launcher must provide

| # | Promise | Why |
| --- | --- | --- |
| L1 | A signed-in account that owns Minecraft: Java Edition, before Play | the owner gate; online-mode servers; Mojang's EULA |
| L2 | A session JSON handed over privately (stdin or a 0600 file) | tokens must not be on a command line |
| L3 | A writable data folder the player can find and back up | instances, store, secrets |
| L4 | The exact options the build lists, and no others | an unlisted option exits 2 |
| L5 | A visible error with the log/crash path when the game fails | players cannot debug exit 1 |
| L6 | Consent for anything that leaves the machine | `policy.telemetry` is off by default |
| L7 | A way to update and roll back a build | Nightlies are deleted after seven days |

## HorizonPort provides

| # | Guarantee | Where |
| --- | --- | --- |
| H1 | A build installs only if `SHA256SUMS.sig` verifies and the archive hash matches | `sign.py`, `fetch.py` |
| H2 | An archive can't write outside its folder (no `..`, no absolute path, no links) | `fetch.extract` |
| H3 | Resources are prepared once per (build, Minecraft, layout) and reused | `prepare.ensure` |
| H4 | A prepared tree's identity is a digest of its contents, not a timestamp | `util.digest_tree` |
| H5 | A `.hmod` is refused before install when the engine would refuse it | `mods.check` |
| H6 | Builds are deterministic (two builds of the same mod are byte-identical) | `mods.build` |
| H7 | No entry point ever puts a token in argv or a log | `launch.py`, `auth.py` |
| H8 | Machine-readable output for every command (`--json`) | `cli.py` |

## The player, in one table

| Moment | What the player sees | What is downloaded |
| --- | --- | --- |
| First launch, signed out | "Sign in with a Microsoft account that owns Minecraft" | nothing |
| Sign-in | a code, a browser page, then their name | nothing |
| Adding the first Horizon instance | a progress bar, minutes | the build (~100 MB), the game files (~1 GiB), the prepared tree (~2–4 GiB) |
| Adding a second instance | a pause of seconds | nothing |
| Play | the game window | nothing |
| Updating to a new build | a progress bar | the new build, and a new prepared tree |
| Adding a mod | the mod appears in the list, off or on | the `.hmod` only (~KBs–MBs) |
| Removing everything | "this deletes N GB" | — |

## Files and formats

All JSON, all versioned, all with a schema in [`schemas/`](schemas).

### `port.config.json`

```json
{
  "horizonport": 1,
  "name": "My Launcher",
  "description": "A launcher that plays Horizon.",
  "engine": { "repo": "horizon-rust/horizon", "tag": "nightly", "commit": null },
  "minecraft": "26.3",
  "paths": { "data": ".horizonport" },
  "launch": { "width": 1280, "height": 720, "fullscreen": false },
  "adapter": { "kind": "node", "entry": "adapter/index.mjs" },
  "policy": { "requireSignature": true, "ownerGate": true, "telemetry": false, "keepBuilds": 2 },
  "auth": { "clientId": null },
  "keys": null,
  "created": "2026-11-14T00:00:00Z"
}
```

`auth.clientId` may be `null` and supplied by `HORIZONPORT_CLIENT_ID` or per command; a port that ships to
players sets it. `keys` names a release-key file to trust instead of Horizon's (a fork that signs its own
builds). Schema: [`schemas/port.config.schema.json`](schemas/port.config.schema.json).

### `instance.json`

Under `<data>/instances/<name>/instance.json`. `build` is a tag under `store/builds/`; `prepared` is a key in
`store/index.json`; `settings` are the launch defaults. The game never reads it. Schema:
[`schemas/instance.schema.json`](schemas/instance.schema.json).

### `store/index.json`

The download-once ledger: one entry per build, prepared tree and Mojang download, each with `digest`, `files`,
`bytes`, `verified` and `refs`. `horizonport store verify` recomputes digests. Schema:
[`schemas/store-index.schema.json`](schemas/store-index.schema.json).

### The launch plan

`horizonport play NAME --dry-run --json` prints the exact `argv`, `cwd`, `env` and session transport.
Schema: [`schemas/launch-plan.schema.json`](schemas/launch-plan.schema.json).

### `horizonport-bundle.json`

What a port ships, and its proof: builds with archive hashes, prepared trees with digests, the Launch API and
the policy. No content. Schema: [`schemas/horizonport-bundle.schema.json`](schemas/horizonport-bundle.schema.json).

## Environment variables

| Variable | Read by | Meaning |
| --- | --- | --- |
| `HORIZONPORT_DATA` | a port, if it honours it | where data goes, overriding `paths.data` |
| `HORIZONPORT_CLIENT_ID` | `auth`, `doctor` | the Azure client ID, when the config has none |
| `HORIZONPORT_ACCOUNT` | `auth`, `play` | which stored account (name or UUID) to use |
| `HORIZONPORT` | the Node/Rust adapters | where the toolkit checkout is |
| `HORIZON_MINECRAFT_DIR`, `MINECRAFT_DIR` | `prepare`, `doctor` | where another launcher keeps the game |
| `JAVA_HOME`, `PATH` | `horizon-prepare` | the Java 25 runtime (also `--java-home`) |
| `HORIZON_PREPARE_JOBS` | `horizon-prepare` | threads for copying/hashing (default: cores, at most 8) |
| `NO_COLOR` | the CLI | plain output |

The engine's own variables (`HORIZON_HOME`, `HORIZON_NO_AUDIO`, `HORIZON_OLDER_SERVERS`, ...) belong to the
game; see [`docs/native-client.md`](../docs/native-client.md).

## Exit codes

`horizonport` follows the engine's convention: **0** success, **1** a failure with a message, **2** a refused
command line or a missing project. `horizonport play` returns the **game's** exit code unchanged (0, 1, 2,
101), so a launcher can pass it straight through — see [`launch.md`](launch.md).

## Versioning

| Thing | Version | May change |
| --- | --- | --- |
| Launch API | `0.1.x` (experimental) | within the line: additions only; a break starts `0.2` |
| `port.config.json` schema | `1` | never in place; a new schema number instead |
| `instance.json` schema | `1` | as above |
| store index schema | `1` | as above |
| bundle schema | `1` | as above |
| mod manifest API | `0.2` (content) | as [`docs/api/stability.md`](../docs/api/stability.md) says |
| HorizonPort toolkit | `1.x` (`--version`) | additions; a break bumps the contract |

Readers ignore fields they do not know; writers never write a schema newer than they declare. A store index
from a newer schema is refused with a message, never half-read.

## What the contract deliberately leaves to the launcher

News, chat, friends, cosmetics, shop, accounts UI, save/world management beyond the folders, mod browsing and
its own database. HorizonPort makes the port *work*; the launcher makes it *feel* like itself.
