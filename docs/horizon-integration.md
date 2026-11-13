# Horizon integration: what Horizon's own documentation says, and what JL does

Read from `horizon-rust/horizon`:
`docs/api/launch-guide.md`, `docs/api/launch.md`, `docs/api/launch-reference.md`,
`.github/workflows/game-build.yml`, `.github/workflows/nightly-build.yml`, `xtask/src/main.rs`.

This exists because the same four mistakes were made in a row. They are written down here so
they are not made a fifth time.

## Mistake 1: the wrong artifact

JL downloaded `horizon-launcher-windows-x64.zip` and **ran it as an installer**. That is not the
game — it is the official launcher, in a separate release stream (`launcher@x.y.z`).

From Horizon's own release page:

> **Want to play? Download the Horizon launcher, not the files below.**
> It installs this version and keeps it up to date.

and the assets are labelled **"Game files the launcher installs"**. So `horizon-windows-x64.zip`
**is the game**, and the launcher merely installs it. JL is a launcher; it needs the files.

## Mistake 2: looking one level too high

`game-build.yml` packs a build with:

```sh
7z a -tzip horizon-windows-x64.zip horizon-windows-x64
```

so every file sits inside **one top-level folder named after the archive**. Inside it,
`xtask`'s `package()` writes:

| File | Why |
| --- | --- |
| `horizon-client.exe` | the game |
| `horizon-ctl.exe` | command line / MCP server |
| `horizon-prepare.exe` | turns the player's Minecraft into resources |
| `horizon-server.exe` | dedicated server |
| `exporters/manifest.json` | the Java exporters the preparer needs |
| `research-lock.json` | the pins every game file is checked against |
| `tools/`, `crates/`, `LICENSE`, `PLAY.txt` | sources and licence |

`HorizonBuilds::rootOf()` resolves the real folder (and accepts a flat archive too).
`horizon-prepare` reads `research-lock.json` and `exporters/` **beside its own binary**, so the
working directory must be that folder.

## Mistake 3: assuming the Nightly is on page 1

The repository publishes `launcher@x.y.z` several times a day — **54 of them in the newest 100
releases** — so a Nightly is routinely on page 2 or later.

The moving tag `nightly` always points at the current build:

```
GET /repos/horizon-rust/horizon/releases/tags/nightly
```

That is exact and **immune to pagination**. JL uses it first and falls back to walking up to ten
pages of 100. Dated `nightly-<date>` tags are **deleted after seven days**, so one must never be
pinned while the moving tag exists.

## Mistake 4: assuming Horizon can find JL's Minecraft files

The preparer searches exactly three launchers: the official one, ATLauncher, and the CurseForge
app. Prism/MultiMC/Modrinth/GDLauncher layouts are invisible to it. A version JL had downloaded
itself produced:

> Missing `...\.minecraft\versions/26.3/26.3.json`

JL's layout is not even `.minecraft`-shaped. Prism stores everything shared:

| Piece | JL's location |
| --- | --- |
| version JSON | `<dataRoot>/meta/net.minecraft/<version>.json` |
| client jar | *not kept as `<version>.jar`* — Prism's meta cache downloads it |
| libraries | `<dataRoot>/libraries` |
| assets | `<dataRoot>/assets` |

The `meta/` level is easy to miss: `Meta::BaseEntity::executeTask` resolves
`QDir("meta").absoluteFilePath(localFilename())` and `localFilename()` is
`uid + '/' + version + ".json"`. Looking for `<root>/net.minecraft/<version>.json` — which
is the shape Horizon's own error message suggests — finds nothing even in the right folder.

Do **not** require the client jar. Prism does not keep `<version>.jar` beside the JSON, and
`horizon-prepare` can take it from the version JSON's own `downloads`.

If no version JSON exists at all (JL only keeps one for a version an instance installed),
fetch it from Mojang's `version_manifest_v2.json` and write it to
`<dataRoot>/meta/net.minecraft/<version>.json`. Sending someone off to play the version in
another launcher first is not an acceptable answer.

**An instance folder is never the right folder to choose.** A CurseForge or Prism instance
holds `minecraftinstance.json` / `instance.cfg` and one instance's own files; the version
JSON, libraries and assets live beside the launcher's data, shared.

The documented answer for a launcher with a different layout is to name each piece instead of
using `--minecraft-dir`:

```
--version-json <json> --client-jar <jar> --libraries-dir <dir> --assets-dir <dir>
```

`HorizonMinecraftFiles` finds those four in JL's data root and passes them, so **the files JL
already downloaded are the ones used**. Nobody should have to copy gigabytes into a fake
`.minecraft`, and Horizon should never be asked to read a second copy.

## Mistake 5: guessing JL's layout from Horizon's error message

Horizon said *"Missing .../versions/26.3/26.3.json"*, so the locator looked for
`<dataRoot>/net.minecraft/<version>.json` — neither the official layout nor JL's. Prism's is
`<dataRoot>/meta/net.minecraft/<version>.json`. Read the writer, not the error message.

Also: an instance folder (`minecraftinstance.json`, `instance.cfg`) is never a Minecraft
installation. Never accept one.

## The launch contract

### Ask the build what it supports

```
horizon-client --launch-api
horizon-prepare --launch-api
```

Each prints one JSON object and exits 0. **Pass only the options it lists** — anything else is
refused with exit code 2.

### Prepare

```
horizon-prepare --prepare --server-jar SERVER_JAR --minecraft-dir GAME_DIR \
    --output PREPARED --complete --progress json
```

- `--complete` also copies the sounds and fails unless the result would pass `--check`.
- `--progress json`: every stdout line is one object — `{"message"}`, `{"fraction"}` 0→1, or
  `{"error"}` last with exit code 1. stderr is human text.
- **The first prepare of a version needs `--server-jar`.** Horizon never downloads it and no
  launcher keeps it; it comes from the version JSON's `downloads.server`, for an owner only.
- One `PREPARED` folder serves **every instance** of that build — resources depend on the build
  and the Minecraft version, not the instance.

Run `--check` before every start: fast, reads no game files, exit 1 lists each gap.

### Start

```
horizon-client --resources PREPARED --game-dir INSTANCE --home INSTANCE \
    --width 1280 --height 720 --session-stdin
```

- The session JSON goes on **stdin** (`name`, `uuid`, `access_token`, `user_type: "msa"`,
  optional `xuid`), then close it. **Never on the command line**, where other programs can read
  it. `--session-file` is the alternative; it must be 0600 and is deleted on read.
- `--game-dir` holds saves, `options.txt`, packs, mods and screenshots.
- `--home` holds `logs/latest.log` and `crash-reports/`.

### Exit codes

| Code | Meaning | What the launcher does |
| --- | --- | --- |
| 0 | The player quit | Nothing |
| 1 | Stopped on an error | Show the last stderr line: `Horizon: crash report saved to <path>` |
| 2 | Refused command line | Show stderr; it names the option — a bug in the launcher |
| 101 | Panicked | As 1 |

### The owner gate

Horizon contains **none of Minecraft's code, textures or sounds**. Every step is for a player
signed in with a Microsoft account that **owns Minecraft: Java Edition** — the same gate
`horizon-launcher` applies before every start.

## Where JL implements it

| Step | Where |
| --- | --- |
| Platform archive name | `HorizonBuilds::platformAsset()` |
| Builds unpacked per tag | `HorizonBuilds::buildDir()` → `<dataRoot>/horizon/<tag>` |
| Real folder inside the archive | `HorizonBuilds::rootOf()` |
| Whole-build check | `HorizonBuilds::isComplete()` |
| Download + unpack | `HorizonDownloadTask` |
| Nightly resolution + auto-update | `HorizonUpdateTask` |
| Find JL's Minecraft files | `HorizonMinecraftFiles::locate()` |
| Server jar for the first prepare | `HorizonServerJarTask` |
| Prepare, with JSON progress | `HorizonPrepareTask` |
| Resources per build + version | `HorizonResources::preparedDir()` |
| Launch with session on stdin | `HorizonLaunchStep` |
| Create instance → download | `HorizonCreationTask::downloadHorizon()` |

Two rules that are easy to get wrong:

1. **Updating is a new folder, not a patch.** Ask the new build, check the resources with it,
   prepare again if the check asks, then start it. Keep the old folder until the new one has
   started once. JL keeps every unpacked tag.
2. **A failed check or update never blocks a launch.** Losing the network should not stop
   someone playing the build they already have.

## Still open

- **Native mods.** Building `.hnmod` needs `horizon-launcher`, which is a separate download and
  is not in `horizon-windows-x64.zip`. JL looks beside the client, in its own horizon folder,
  and on `PATH`. Content mods (`.hmod`) are data-only and need no compiler.
- **Linux/macOS.** Horizon ships Linux as `.tar.gz`; JL only has zip extraction. Those
  platforms refuse the download with a clear message instead of saving an unpackable file.
