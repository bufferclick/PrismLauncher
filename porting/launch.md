# Play: what happens when the player presses it

The one button players judge a launcher by. This page is the exact sequence, the arguments, the failure
modes, and the copy to show.

The contract is the engine's **Launch API 0.1.0** — [guide](../docs/api/launch.md),
[reference](../docs/api/launch-reference.md). HorizonPort implements the launcher side of it in
`porting/horizonport/launch.py`.

## The timeline

```text
press Play
  │
  ├─ 1. Is there a session for an owner?                        (0 ms)
  │     no  → show sign-in, stop. Do not start the game.
  │     yes → refresh if it expires within the hour.
  │
  ├─ 2. Does the instance still resolve?                        (ms)
  │     build installed? prepared tree present? instance folders?
  │
  ├─ 3. horizon-prepare --check --output <tree>                 (0.2–2 s)
  │     exit 0 → continue. exit 1 → prepare again (minutes), with progress.
  │
  ├─ 4. Build the argv from --launch-api                        (ms)
  │     only listed options; refuse our own bug with exit 2.
  │
  ├─ 5. Spawn horizon-client, cwd = the build folder.            (0.5–4 s to title screen)
  │     write the session JSON to stdin, close stdin.
  │
  ├─ 6. Wait. Stream nothing (the game owns its window).        (the session)
  │
  └─ 7. It exits: 0 quit · 1 error · 2 our bug · 101 panic.
        On 1/101, the last stderr line is the crash report path.
```

Steps 1–4 are `horizonport play NAME --dry-run`: it prints the plan without spawning, so a launcher can show
the command, log it for support, or diff it against the build's options.

## The command

```sh
horizon-client \
  --resources  <data>/store/prepared/prepared-nightly@26.3@7 \
  --game-dir   <data>/instances/Work/game \
  --home       <data>/instances/Work/home \
  --width      1280 --height 720 \
  [--fullscreen] [--quickPlaySingleplayer Survival | --quickPlayMultiplayer host:port] \
  --session-stdin
```

| Argument | Holds | Notes |
| --- | --- | --- |
| `--resources` | the prepared tree | shared by every instance of the build |
| `--game-dir` | worlds (`saves/`), `options.txt`, `resourcepacks/`, `horizon-mods/`, `screenshots/` | created when missing |
| `--home` | `logs/latest.log`, `crash-reports/` | created when missing |
| `--player-dir` | per-player files when several games share one game folder | optional |
| `--width`, `--height` | window size | clamp to the screen; remember per instance |
| `--fullscreen` | fullscreen for this run | does **not** write `options.txt` |
| `--session-stdin` | the account | preferred; `--session-file` is the fallback |
| `--quickPlaySingleplayer WORLD` | open a world of `saves/` | one folder name; a path is refused |
| `--quickPlayMultiplayer HOST[:PORT]` | join a server | |
| `--launch-api` | prints the reply and exits | ask once per build, cache it in the store entry |

Anything not in the build's `options` exits **2**. That is why the plan is validated, never hardcoded.

## How it ends

| Code | Meaning | What the launcher does |
| --- | --- | --- |
| 0 | The player quit | nothing; record the play time |
| 1 | Stopped on an error | read the last stderr line (`Horizon: crash report saved to <path>`), show a "Horizon crashed" panel with Open report / Open logs / Copy details / Report it |
| 2 | Refused command line | this is **your** bug: log the argv, the build's option list and the game's stderr; never show it to a player as "the game crashed" |
| 101 | Panicked | as 1 |
| 130 / other | killed by a signal | as 1, with "the game was closed by the system" |

On success, `playCount` and `lastPlayed` in `instance.json` are updated by `horizonport play`. A launcher with
its own database should do the same there.

## The session handover, in code

Node (`templates/adapter-node/launch.mjs`):

```js
const child = spawn(plan.argv[0], plan.argv.slice(1), {
  cwd: plan.cwd, env: { ...process.env, ...plan.env },
  stdio: ["pipe", "inherit", "pipe"],
});
child.stdin.end(JSON.stringify(session) + "\n");
```

Rust (`templates/adapter-rust/src/lib.rs`): `Stdio::piped()` for stdin, `write_all(json)`, close, then
`wait_with_output()` for stderr.

Both write **nothing** to disk and pass **no** token in argv. If your UI framework cannot pipe stdin (some
menu-bar wrappers), write a 0600 file in the data folder, delete it as soon as the process starts, and prefer
`--session-stdin` on every platform that can.

## Logs and crash reports

* `logs/latest.log` in `--home`; previous runs are archived as `logs/<date>-<n>.log.gz`.
* `crash-reports/crash-<date>_<time>-client.txt` beside them, and its path printed last on stderr.
* Two buttons players need: **Open logs folder** and **Copy crash report path**. A third that helps you:
  **horizonport check --support** writes a JSON bundle with no tokens and no worlds.

Do not parse the log to decide whether the game started. The process and the exit code are the truth.

## Worlds and saves

* One folder per world under `<game-dir>/saves/`.
* `--quickPlaySingleplayer NAME` opens an existing world; a missing world falls back to the title screen —
  check `saves/<name>` first if the player clicked a specific world.
* Backups are the launcher's job: copy the save folder while the game is closed, or use the engine's own
  `/save-all` + copy. Never copy a region file from a running world.
* A Java edition save opens as it is; worlds from 1.8 to 26.2 are upgraded by the engine. Warn before
  opening an old world (upgrading is forward-only).

## Offline, and what it means

* With no network after a successful owner check, the last answer stands and the game starts without a
  session: single player and LAN work, online-mode servers refuse the player.
* `horizonport play --offline` exists to test an adapter; it prints a warning and is not part of a shipped UI.
* There is deliberately no "offline mode" login, no offline UUIDs, no "skip the gate" switch. The engine's
  policy (`docs/microsoft-account.md`, "The owner gate") is the port's policy.

## First start is not the same as every start

| Start | What it does | Time (desktop, 2026 hardware) |
| --- | --- | --- |
| The very first | downloads the build, the game files, prepares | minutes |
| First of a new build | prepares that build's resources | 1–5 minutes |
| Any later | `--check`, then the game | 1–3 s to the title screen |

So the Play button has two states the UI should distinguish: **Play** and **Install / Repair**, with the
reason ("first run", "this build needs new resources", "the files changed"). Never a disabled Play with no
explanation.

## Things that go wrong, and the fix

| Symptom | Cause | Fix |
| --- | --- | --- |
| Nothing happens, instant exit 2 | an unlisted option | use the plan from `--dry-run`; check `--launch-api` |
| Window opens then closes | GPU/driver, or resources missing | read `logs/latest.log`; run `horizon-prepare --check` |
| "not signed in" on stderr | bad or expired session | sign in again; check `user_type: "msa"` |
| Online server: "Failed to verify username" | no/expired session | refresh the token before launch |
| Black screen on Linux | Vulkan/OpenGL driver | check the GPU requirements in the README |
| Extremely slow first world | chunk generation | normal; the second visit is fast |
| Audio missing | sounds were never copied (`--complete`) | prepare again with `--complete` |
| Game starts in the wrong folder | `cwd`/`--game-dir` mixed up | pass both explicitly; the plan does |
| Two instances fight over options | both use the same `--game-dir` | one game folder per instance, always |

## Performance the launcher can claim honestly

The engine's own numbers (README, "Performance") are measured on a fixed machine with its launcher's
settings. A port should not promise numbers; it should promise **parity with the same build on the same
machine**, which is what matters. Two launcher-side things change perceived speed:

1. **Do not re-verify the world's resources on every start.** `--check` is the fast one; the full digest is
   for `check --full`, not for Play.
2. **Do not re-initialise the store.** Loading `store/index.json` and one `--check` is all Play needs;
   scanning the whole store on every launch is what makes launchers feel slow.
