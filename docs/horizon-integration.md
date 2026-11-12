# Horizon integration: what Horizon's own documentation says, and what JL does

Read from `horizon-rust/horizon`:
`docs/api/launch-guide.md`, `docs/api/launch.md`, `docs/api/launch-reference.md`,
`.github/workflows/game-build.yml`, `.github/workflows/nightly-build.yml`, `xtask/src/main.rs`.

## The mistake that was in JL

JL downloaded `horizon-launcher-windows-x64.zip` (from the `launcher@0.2.62` release
stream) and **ran it as an installer**. That is not the game — it is the official
launcher, a separate program in a separate release stream.

That is why Help said *"Found horizon-launcher-windows-x64.zip in release launcher@0.2.62
… Launching the Horizon installer…"* and instances still could not launch. The installer
probably ran fine; JL was pointing at the wrong artifact the whole time.

From Horizon's own release page:

> **Want to play? Download the Horizon launcher, not the files below.**
> It installs this version and keeps it up to date.

and the assets are labelled:

> **Game files the launcher installs:** Windows / Linux / macOS

So `horizon-windows-x64.zip` **is the game files**, and the launcher is a *different*
download that merely installs them. JL is a launcher, so JL needs the second thing.

## The contract JL implements

### 1. A build is one archive per platform

| Platform | Archive |
| --- | --- |
| Windows x64 | `horizon-windows-x64.zip` |
| Windows ARM64 | `horizon-windows-arm64.zip` |
| Linux x86_64 | `horizon-linux-x86_64.tar.gz` |
| macOS Apple silicon | `horizon-macos-arm64.zip` |
| macOS Intel | `horizon-macos-x64.zip` |

### 2. The archive is NOT flat

`game-build.yml` packs a build with:

```sh
7z a -tzip horizon-windows-x64.zip horizon-windows-x64
```

so every file sits inside **one top-level folder named after the archive**. Inside that
folder, `xtask`'s `package()` writes:

| File | Why |
| --- | --- |
| `horizon-client.exe` | the game |
| `horizon-ctl.exe` | command line / MCP server |
| `horizon-prepare.exe` | turns the player's Minecraft into resources |
| `horizon-server.exe` | dedicated server |
| `exporters/manifest.json` | the Java exporters the preparer needs |
| `research-lock.json` | the pins every game file is checked against |
| `tools/`, `crates/`, `LICENSE`, `PLAY.txt` | sources and licence |

Looking one level too high is a silent failure: the files are all there, just not where
you asked. `HorizonBuilds::rootOf()` resolves the real folder and accepts a flat archive
too. `horizon-prepare` reads `research-lock.json` and `exporters/` **beside its own
binary**, so the working directory must be that folder.

### 3. The Nightly is buried behind launcher releases

The same repository publishes `launcher@x.y.z` several times a day — **54 of them in the
newest 100 releases**. A Nightly is routinely on page 2, so "scan the first page" finds
only launcher builds.

The moving tag `nightly` always points at the current build, and

```
GET /repos/horizon-rust/horizon/releases/tags/nightly
```

is exact and **immune to pagination**. JL uses that first, and falls back to walking up
to ten pages of 100. Dated `nightly-<date>` tags are **deleted after seven days**, so a
dated tag must never be pinned while the moving one exists.

### 4. Every start: ask the build what it supports

```
horizon-client --launch-api
horizon-prepare --launch-api
```

Each prints one JSON object and exits 0. **Pass only the options it lists** — anything
else is refused with exit code 2.

### 5. Preparing

```
horizon-prepare --prepare --server-jar SERVER_JAR --minecraft-dir GAME_DIR \
    --output PREPARED --complete --progress json
```

- `--complete` also copies the sounds and fails unless the result would pass `--check`.
- `--progress json`: every stdout line is one object — `{"message"}`, `{"fraction"}` 0→1,
  or `{"error"}` last with exit code 1. stderr is human text.
- **Horizon downloads none of Mojang's files.** It reads the player's own copy and checks
  every file against the pins in `research-lock.json`.
- One `PREPARED` folder serves **every instance** of that build, because resources depend
  on the build and the Minecraft version, not the instance.

Run `--check` before every start: fast, reads no game files, exit 1 lists each gap.

### 6. Starting

```
horizon-client --resources PREPARED --game-dir INSTANCE --home INSTANCE \
    --width 1280 --height 720 --session-stdin
```

- The session JSON goes on **stdin** (`name`, `uuid`, `access_token`, `user_type: "msa"`,
  optional `xuid`), then close it. **Never on the command line**, where other programs can
  read it. `--session-file` is the alternative; it must be 0600 and is deleted on read.
- `--game-dir` holds saves, `options.txt`, packs, mods and screenshots.
- `--home` holds `logs/latest.log` and `crash-reports/`.

### 7. Exit codes

| Code | Meaning | What the launcher does |
| --- | --- | --- |
| 0 | The player quit | Nothing |
| 1 | Stopped on an error | Show the last stderr line: `Horizon: crash report saved to <path>` |
| 2 | Refused command line | Show stderr; it names the option — a bug in the launcher |
| 101 | Panicked | As 1 |

### 8. Owner gate

Horizon contains **none of Minecraft's code, textures or sounds**. Every step is for a
player signed in with a Microsoft account that **owns Minecraft: Java Edition** — the same
gate `horizon-launcher` applies before every start.

## Where JL implements it

| Step | Where |
| --- | --- |
| Platform archive name | `HorizonBuilds::platformAsset()` |
| Builds unpacked per tag | `HorizonBuilds::buildDir()` → `<dataRoot>/horizon/<tag>` |
| Real folder inside the archive | `HorizonBuilds::rootOf()` |
| Whole-build check | `HorizonBuilds::isComplete()` |
| Download + unpack | `HorizonDownloadTask` |
| Nightly resolution + auto-update | `HorizonUpdateTask` |
| Prepare, with JSON progress | `HorizonPrepareTask` |
| Resources per build + version | `HorizonResources::preparedDir()` |
| Launch with session on stdin | `HorizonLaunchStep` |
| Create instance → download | `HorizonCreationTask::downloadHorizon()` |

Two rules that are easy to get wrong:

1. **Updating is a new folder, not a patch.** Ask the new build, check the resources with
   it, prepare again if the check asks, then start it. Keep the old folder until the new
   one has started once. JL keeps every unpacked tag.
2. **A failed check or update never blocks a launch.** Losing the network should not stop
   someone playing the build they already have.

## Still open

- **Native mods.** Building `.hnmod` needs `horizon-launcher`, which is a separate
  download from the game files and is not in `horizon-windows-x64.zip`. JL looks beside
  the client, in its own horizon folder, and on `PATH`. Content mods (`.hmod`) are
  data-only and need no compiler.
- **Linux/macOS.** Horizon ships Linux as `.tar.gz`; JL only has zip extraction. Those
  platforms refuse the download with a clear message instead of saving an unpackable file.
- **Server jar.** `--server-jar` is needed for the *first* prepare. Horizon never
  downloads it; the launcher must fetch the version JSON's `downloads.server`, for an
  owner only. JL does not do this yet, so a first prepare can ask for it.
