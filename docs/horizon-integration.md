# Horizon integration: what Horizon's own documentation says, and what JL now does

Read from `horizon-rust/horizon` on 2026-11-10:
`docs/api/launch-guide.md`, `docs/api/launch.md`, `docs/api/launch-reference.md`.

## The mistake that was in JL

JL downloaded `horizon-launcher-windows-x64.zip` (from the `launcher@0.2.62` release
stream) and **ran it as an installer**. That is not the game. It is the official
launcher, a separate program in a separate release stream.

That is exactly why Help said *"Found horizon-launcher-windows-x64.zip in release
launcher@0.2.62 … Launching the Horizon installer…"* and then instances still could not
launch and Build Mods still said *"Horizon launcher not found"*. The installer finished;
the game files it was supposed to leave behind were never where JL looked, because JL
was pointing at the wrong artifact the whole time.

From the v0.2.97 release page, in Horizon's own words:

> **Want to play? Download the Horizon launcher, not the files below.**
> It installs this version and keeps it up to date.

and the assets are labelled:

> **Game files the launcher installs:** Windows / Linux / macOS

So `horizon-windows-x64.zip` **is the game files**, and the launcher is a *different*
download that merely installs them. JL is a launcher, so JL needs the second thing.

## The contract JL now implements

### 1. A build is one archive per platform

| Platform | Archive |
| --- | --- |
| Windows x64 | `horizon-windows-x64.zip` |
| Windows ARM64 | `horizon-windows-arm64.zip` |
| Linux x86_64 | `horizon-linux-x86_64.tar.gz` |
| macOS Apple silicon | `horizon-macos-arm64.zip` |
| macOS Intel | `horizon-macos-x64.zip` |

- The newest build is the release tagged **`nightly`** — rebuilt from `main` every few
  hours. `nightly-<date>` tags are **deleted after seven days**, so a dated tag must
  never be stored as a permanent pin. Stable tags like `v0.2.97` persist.
- Unpack into a folder of its own and **keep it whole**: `horizon-client`,
  `horizon-prepare`, `research-lock.json` and `exporters/` work together. JL verifies
  all three before treating a folder as a build, and refuses a partial unpack.

### 2. Every start: ask the build what it supports

```
horizon-client --launch-api
horizon-prepare --launch-api
```

Each prints one JSON object and exits 0. **Pass only the options it lists — anything
else is refused with exit code 2.**

### 3. Preparing

```
horizon-prepare --prepare --server-jar SERVER_JAR --minecraft-dir GAME_DIR \
    --output PREPARED --complete --progress json
```

- `--complete` also copies the sounds and fails unless the result would pass `--check`.
- `--progress json`: every stdout line is one object — `{"message"}`, `{"fraction"}` 0→1,
  or `{"error"}` as the last line with exit code 1. stderr is human text.
- **Horizon downloads none of Mojang's files.** It reads the player's own copy and
  checks every file against the pins in `research-lock.json`.
- One `PREPARED` folder serves **every instance** of that build, because the resources
  depend on the build and the Minecraft version, not on the instance.

The guide asks for a `--check` **before every start** — fast, reads no game files, exit
1 lists each gap. A new build that writes a newer layout makes older resources fail.

### 4. Starting

```
horizon-client --resources PREPARED --game-dir INSTANCE --home INSTANCE \
    --width 1280 --height 720 --session-stdin
```

- The session JSON goes on **stdin** (`name`, `uuid`, `access_token`, `user_type: "msa"`,
  optional `xuid`), then close it. **Never on the command line**, where other programs can
  read it. `--session-file` is the alternative; it must be 0600 and is deleted on read.
- `--game-dir` holds saves, `options.txt`, packs, mods and screenshots.
- `--home` holds `logs/latest.log` and `crash-reports/`.

### 5. Exit codes

| Code | Meaning | What the launcher does |
| --- | --- | --- |
| 0 | The player quit | Nothing |
| 1 | Stopped on an error | Show the last stderr line: `Horizon: crash report saved to <path>` |
| 2 | Refused command line | Show stderr; it names the option — a bug in the launcher |
| 101 | Panicked | As 1 |

### 6. Owner gate

Horizon contains **none of Minecraft's code, textures or sounds**. Every step is for a
player signed in with a Microsoft account that **owns Minecraft: Java Edition** — the
same gate `horizon-launcher` applies before every start.

## What JL 0.0.7 does

| Step | Where |
| --- | --- |
| Platform archive name | `HorizonBuilds::platformAsset()` |
| Builds unpacked per tag | `HorizonBuilds::buildDir()` → `<dataRoot>/horizon/<tag>` |
| Whole-build check | `HorizonBuilds::isComplete()` |
| Download + unpack | `HorizonDownloadTask` |
| `nightly` resolution + auto-update | `HorizonUpdateTask` |
| Prepare, with JSON progress | `HorizonPrepareTask` |
| Resources per build + version | `HorizonResources::preparedDir()` |
| Launch with session on stdin | `HorizonLaunchStep` |
| Create instance → download | `HorizonCreationTask::downloadHorizon()` |

Two rules the code follows that are easy to get wrong:

1. **Updating is a new folder, not a patch.** Per the guide: ask the new build, check the
   resources with it, prepare again if the check asks, then start it. Keep the old folder
   until the new one has started once. JL keeps every unpacked tag.
2. **A failed check or update never blocks a launch.** Losing the network should not stop
   someone playing the build they already have.

## Still open

- **Native mods.** Building `.hnmod` needs `horizon-launcher`, which is a separate
  download from the game files and does not come in `horizon-windows-x64.zip`. JL looks
  for it beside the client, in its own horizon folder, and on `PATH`. Without it, Build
  Mods cannot compile — content mods (`.hmod`) are data-only and need no compiler.
- **Linux/macOS.** Horizon ships Linux as `.tar.gz`; JL only has zip extraction. Those
  platforms refuse the download with a clear message instead of saving a file it cannot
  unpack.
- **Server jar.** `--server-jar` is needed for the *first* prepare. Horizon never
  downloads it; the launcher must fetch the version JSON's `downloads.server`, for an
  owner only. JL does not do this yet, so a first prepare can ask for it.
