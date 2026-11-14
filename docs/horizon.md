# Horizon in JL

JL plays **Horizon** — Minecraft: Java Edition 26.3 rewritten in Rust — alongside
ordinary Minecraft instances. Horizon is a native client: it has no JVM, no
version JSON and no Java mods. This document is how JL installs it, prepares it,
launches it and manages its content, and which parts JL is allowed to touch.

The engine and the porting kit live in
[`horizon-rust/horizon`](https://github.com/horizon-rust/horizon). The toolkit JL
uses is vendored at [`porting/horizonport`](../porting/horizonport) under MIT.

## The one rule

**JL implements none of the risky parts.** Signature verification, archive
unpacking, Mojang downloads, resource preparation, launch-command validation and
`.hmod` checking are all done by `porting/horizonport`, called as a subprocess
with `--json`. There is exactly one implementation of each, and it is the
audited one. A second downloader would be a second set of bugs in the place
where a bug means "installed a tampered binary".

`launcher/minecraft/horizon/HorizonPort.cpp` is the only place JL talks to it.

## What the player sees

| Moment | What happens |
| --- | --- |
| New instance → **Horizon** → OK | JL fetches the signed Horizon build, downloads Minecraft 26.3 for the signed-in owner, prepares the resources once, and creates the instance. One dialog, no folder picking, no installer. |
| Press **Play** | JL asks the toolkit for the launch command, starts `horizon-client`, hands it the session on stdin, and reports the exit code. |
| Add a mod | JL checks the `.hmod` with the toolkit before copying it into `game/horizon-mods/`, then writes `mod.<id>:true` to `horizon-mods.txt`. |
| Add a second instance | Nothing is downloaded. The prepared tree is shared. |
| Horizon updates | Fetch the new build, prepare it, create an instance on the new tag. The game files are reused. |

## Layout on disk

Everything JL creates for Horizon lives under the launcher's data folder, never
in the instance and never in the installation:

```text
<JL data>/horizonport/
  port.config.json            the port's identity and policy
  store/builds/<tag>/         the signed Horizon build
  store/mojang/26.3/          the owner's game files (downloaded once)
  store/prepared/<key>/       horizon-prepare's output (once per build)
  store/index.json            digests and sizes
  instances/<name>/           the toolkit's own instance records
  secrets/<uuid>.json         the account, mode 0600
  accounts.json               names and UUIDs only, never a token
```

The instance folder itself stays where every JL instance lives, and holds the
worlds, `options.txt`, `resourcepacks/`, `screenshots/` and `horizon-mods/`.

## Sign-in

Horizon plays only with an account that **owns Minecraft: Java Edition**, and the
account that plays must be the account that owns it. JL already signs players in
with Microsoft, so Horizon reuses that account; nothing is signed in twice.

The session JSON goes to the game's **stdin** and stdin is closed immediately.
It is never on a command line, in the environment, or in a file.

If no account is set up, Play refuses and says so rather than starting a game
that cannot join a server.

## The launch command

JL does not hardcode Horizon's options. It asks:

```sh
horizonport play <instance> --dry-run
```

which returns the exact `argv`, validated against the build's own
`--launch-api` reply. An option a build does not list can never be passed,
because the toolkit refuses to build the command.

Exit codes, and what JL does with them:

| Code | Meaning | JL shows |
| --- | --- | --- |
| 0 | the player quit | nothing |
| 1 | stopped on an error | the crash report path from the last stderr line |
| 2 | the command line was refused | "this is a bug in JL", plus the log |
| 101 | panicked | the crash report path |

## Content mods

Horizon reads `.hmod` content mods from `game/horizon-mods/` and enables each
one with a `mod.<id>:true` line in `game/horizon-mods.txt` — the same file the
game's own Options → Mods screen writes, so the two views never disagree.

Java mods (`.jar`) do not run: Horizon has no JVM. Native mods (`.hnmod`) are
compiled into the engine and need a custom unsigned build, which a launcher that
installs signed builds cannot offer. The mod page says so instead of pretending
otherwise.

## Policy

These are not configurable, and JL has no switch for any of them:

- `requireSignature: true` — a build installs only if `SHA256SUMS.sig` verifies
  and the archive's SHA-256 matches.
- `ownerGate: true` — the game starts only for an account that owns it.
- `telemetry: false` — nothing leaves the machine.
- No offline login, no signature bypass, no owner-gate bypass. There is no
  hidden button and no environment variable for any of them.

## Requirements

- **Python 3.11+** on PATH. The toolkit is pure standard library; there is
  nothing to `pip install`.
- Disk: about 1 GiB for the build, ~1 GiB for the game files and 2–4 GiB for the
  prepared resources, once per build.
- Network at first run: GitHub (the build), Mojang (the game files).

Java is **not** required to play Horizon. It is used by `horizon-prepare` while
resources are prepared; if no suitable Java is found the toolkit says so in
plain language and JL shows that message.

## Verifying a build of JL

```sh
python -m porting.horizonport doctor
python -m porting.horizonport check --full
python -m unittest porting.tests.test_horizonport_sign porting.tests.test_horizonport_config \
                   porting.tests.test_horizonport_fetch porting.tests.test_horizonport_mods \
                   porting.tests.test_horizonport_launch porting.tests.test_horizonport_cli
```

The release workflow runs the same checks on Windows and refuses to publish a
portable zip that does not contain the toolkit.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| "Python 3.11 or newer is required" | Python missing or too old | install Python 3.11+ and restart JL |
| Play refuses immediately | no account, or the account was never signed in | add the Microsoft account in Accounts |
| "This account doesn't own Minecraft" | the account does not own the game | sign in with the account that bought it (Game Pass counts) |
| The first instance takes a long time | it downloads ~1 GiB of game files and prepares 2–4 GiB | normal, once per build; later instances are instant |
| "Horizon refused the command line (exit 2)" | JL passed an option the build does not take | report it with the log: it is a bug in JL |
| Stuck at "Preparing resources" | preparation is CPU-bound, minutes | watch the log; finished work is kept if it fails |
