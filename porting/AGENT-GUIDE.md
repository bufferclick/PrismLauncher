# HorizonPort: the agent guide

**Feed this file to your AI agent.** It is self-contained: it says what the job is, which files are the
truth, the exact order of work, the command for each step, and how to prove each step is done. An agent that
follows it end to end produces a launcher that installs Horizon, prepares its resources once, plays it with
the player's own Microsoft account, and manages mods — without reading the other 60 documents in this
repository.

If you are an agent and you can only read one file, read this one twice. Then read
[`contract.md`](contract.md) for the tables and [`PORTING.md`](../PORTING.md) when a step surprises you.

---

## 0. Mission

> Turn the launcher in this repository into a launcher that can play **Horizon** — Minecraft: Java Edition
> 26.3 rewritten in Rust — with the same relationship a launcher has with vanilla: sign in, add an instance,
> press Play, manage mods.

"Done" means a player, with a Microsoft account that owns Minecraft: Java Edition, can:

1. sign in inside your launcher;
2. add a Horizon instance (the first one downloads what it needs; later ones do not);
3. press Play and get the game window;
4. add, turn off and remove content mods that the game loads;
5. update to a new Horizon build without downloading the game again;
6. see a plain-language error when something fails, with the log or crash report one click away.

## 1. Ground truth (read these before writing code)

In this repository, these files define what you may do. Do not contradict them; if one seems wrong, stop
and say so in your report rather than inventing a different behaviour.

| File | What it settles |
| --- | --- |
| [`docs/api/launch.md`](../docs/api/launch.md) | the Launch API: options, session JSON, exit codes, preparing |
| [`docs/api/launch-reference.md`](../docs/api/launch-reference.md) | every option and the `--launch-api` reply |
| [`docs/api/content.md`](../docs/api/content.md) | where mods, packs and shaders go; how they turn on |
| [`docs/api/mod-files.md`](../docs/api/mod-files.md) | what a `.hmod` is, byte for byte |
| [`docs/microsoft-account.md`](../docs/microsoft-account.md) | the seven sign-in steps, the owner gate, tokens |
| [`docs/api/stability.md`](../docs/api/stability.md) | what may change without notice (Launch API 0.1 is experimental) |
| [`porting/contract.md`](contract.md) | the contract *your* launcher implements, in tables |
| [`porting/assets.md`](assets.md) | the download-once design, in detail |
| [`porting/CHECKLIST.md`](CHECKLIST.md) | the seven gates you must pass before shipping |

The toolkit's code is `porting/horizonport/`. It is plain Python 3.11+, standard library only. Read it
rather than reimplementing it: `sign.py` (Ed25519 + checksums), `fetch.py` (verify and unpack a build),
`mojang.py` (download the owner's game files), `prepare.py` (resources, once), `launch.py` (the Launch API),
`mods.py` (content mods), `store.py` (the download-once store).

## 2. Invariants (violating any of these is a failed port)

1. **No Minecraft files in Git, ever.** No jars, assets, prepared resources, decompiled sources. The
   repository's own check rejects them (`tools/check_public_tree.py`).
2. **No build without a verified signature.** `SHA256SUMS` + `SHA256SUMS.sig` (Ed25519) or nothing. Never
   disable this in code a player runs.
3. **The owner gate stays on.** The game starts only for an account that owns Minecraft: Java Edition.
   `policy.ownerGate` is `true`; there is no bypass flag.
4. **Tokens never touch the command line or a log.** The session JSON goes to the child's stdin, or to a
   0600 file the game deletes. Never `echo` a token, never `printf` it into a shell, never put it in argv.
5. **Only options the build lists.** Ask `horizon-client --launch-api`; an unlisted option exits 2. Never
   hardcode an option list that could drift from the build.
6. **Telemetry stays off unless the player turns it on.** `policy.telemetry` is `false`.
7. **Prepared resources are made on the player's machine, from the player's own files.** You may bundle
   *code* and *digests*, never Mojang's content.
8. **Never write to a player's real folders during development.** Use a scratch project folder and
   `HORIZONPORT_DATA`; never `~/.local/share/horizon`, `~/.minecraft`, or any real launcher's data.
9. **Unknown keys fail loudly.** The toolkit refuses unknown config keys and unknown mod-manifest keys on
   purpose; do not "tolerate" them in adapter code either.
10. **One implementation of the risky parts.** Shell out to `horizonport` (or import `porting.horizonport`)
    for signature checks, archives, digests and preparation. Do not write a second downloader.

## 3. Environment

* Python 3.11+ (`python3 -m porting.horizonport --version`).
* Java 25 for preparation (`horizon-prepare` runs Mojang's exporters), unless the build ships/uses its own.
* Disk: ~1 GiB for a build, ~2–4 GiB for prepared resources with sounds, plus the game files (~1 GiB).
* Network at first run: GitHub (release), Mojang (game files), Microsoft (sign-in). Never a mirror.

Run this first and fix every `FAIL` before writing code:

```sh
python3 -m porting.horizonport doctor
```

## 4. The work, in phases

Each phase has a command, an artefact and an acceptance check. Do them in order; do not start a phase
before the previous one's check passes. When a phase cannot pass in your environment (no Java, no Minecraft
account), stop at that phase, record the failure verbatim in your report, and do not fake the result.

### Phase 0 — Make the port project

```sh
python3 -m porting.horizonport init ~/MyLauncher --name "My Launcher" --adapter node
cd ~/MyLauncher
python3 -m porting.horizonport check
```

**Artefacts:** `port.config.json`, `adapter/`, `schemas/`, `AGENT-GUIDE.md`, `CHECKLIST.md`, `.gitignore`.
**Accept:** `check` exits 0. `port.config.json` parses; `engine.repo`, `engine.tag`, `minecraft` and
`policy` are the ones you intend.

### Phase 1 — Install a build, verified

```sh
python3 -m porting.horizonport fetch --tag nightly
```

**Accept:** exit 0; `store/builds/nightly/` holds `horizon-client`, `horizon-prepare`,
`research-lock.json`; `store/index.json` has a `build:nightly` entry with a digest and an `archiveSha256`.
Try once with a deliberately wrong `--keys` file and confirm **nothing is installed** — that is the test
that the signature check is wired, not skipped.

### Phase 2 — Sign-in

Register your own Azure app (see [`auth.md`](auth.md)); never reuse Horizon's client ID or another
launcher's. Then:

```sh
python3 -m porting.horizonport auth sign-in --client-id <YOUR-GUID>
```

**Accept:** you see a code, the browser flow completes, and the command prints the account's name and UUID
with "owns Minecraft: Java Edition". `~/.local/share/horizonport/…/secrets/<uuid>.json` exists with mode
0600, and `accounts.json` contains **no** token. If the account does not own the game, the command must
fail with the owner message — verify that too.

### Phase 3 — Prepare once

```sh
python3 -m porting.horizonport prepare --download          # uses the signed-in owner
# or, if the machine already has 26.3 from any launcher:
python3 -m porting.horizonport prepare --from-install ~/.minecraft
```

**Accept:** exit 0; `store/prepared/<key>/` exists; `horizon-prepare --check` (run by the toolkit) passes;
the index has a `prepared:` entry whose `build` and `minecraft` match the build's `--launch-api` reply.
Run it a second time: it must reuse the tree in seconds, not download.

### Phase 4 — The first instance, and Play

```sh
python3 -m porting.horizonport instance new Work
python3 -m porting.horizonport play Work --dry-run   # inspect argv
python3 -m porting.horizonport play Work
```

**Accept:** the game window opens, the title screen appears, and quitting exits 0. `instance.json` records
`build`, `prepared`, `settings`; the second instance (`instance new Second`) reuses `prepared` and starts in
seconds. `play --dry-run` must name only options the build listed.

### Phase 5 — Mods

```sh
python3 -m porting.horizonport mod new ruby-mod
python3 -m porting.horizonport mod build ruby-mod
python3 -m porting.horizonport mod install ruby-mod/target/horizon-mod/ruby_mod.hmod --instance Work
python3 -m porting.horizonport mod list --instance Work
```

**Accept:** the `.hmod` is in `<instance>/game/horizon-mods/`, `horizon-mods.txt` has `mod.ruby_mod:true`,
and the game's Options → Mods shows it. Turn it off with `mod disable` and confirm the game agrees.

### Phase 6 — Update a build without downloading the game

```sh
python3 -m porting.horizonport fetch --tag nightly      # a newer build
python3 -m porting.horizonport prepare                  # a new prepared tree for that build's layout
python3 -m porting.horizonport instance new Next --build nightly
```

**Accept:** the game files under `store/mojang/` are untouched (same bytes, same timestamps); only the
build and its prepared tree are new. Old instances keep playing the old build until you move them.

### Phase 7 — Ship

```sh
python3 -m porting.horizonport check --full
python3 -m porting.horizonport bundle
```

**Accept:** `check --full` exits 0 with no `FAIL`; `dist/horizonport-bundle/` holds
`horizonport-bundle.json`, `adapter/`, `schemas/`, `AGENT-GUIDE.md`, `CHECKLIST.md`, `SHA256SUMS`; the
bundle names each build's archive SHA-256 and each prepared tree's digest; **it contains no game files**.

## 5. Wiring the launcher's UI

The toolkit is the engine of the port; your launcher is the face of it. There are two integration styles,
and both are supported:

1. **Call the CLI** (`--json`) from your process. One implementation, any language. Template:
   [`templates/adapter-node/horizonport.mjs`](templates/adapter-node/horizonport.mjs) and
   [`templates/adapter-rust/src/lib.rs`](templates/adapter-rust/src/lib.rs). A Python launcher copies
   [`templates/adapter-python/adapter.py`](templates/adapter-python/adapter.py).
2. **Start the game yourself** with the plan from `horizonport play --dry-run`, handing the session over on
   stdin. Template: [`templates/adapter-node/launch.mjs`](templates/adapter-node/launch.mjs).

Screens a launcher needs, in the order a player meets them:

| Screen | Calls | Must show |
| --- | --- | --- |
| Sign in | `auth sign-in` (or your own device-code UI) | the code, the browser link, the owner result |
| First run | `fetch`, then `prepare --download` | a progress bar from `--progress json`, a Cancel that keeps finished files |
| Instances | `instance new/list/info/remove` | build, disk use, last played, "shares resources" |
| Play | `play --dry-run`, then `play` | the window; on exit 1/101 the crash report path |
| Mods | `mod list/install/enable/disable/remove` | on/off, version, side, "applies at next start" |
| Updates | `fetch`, `prepare`, `instance new --build` | that the game is not downloaded again |

Rules for the UI:

* Never block the UI on `prepare`; it takes minutes. Show `{fraction}` and `{message}` events.
* A build that fails verification is a **security** event: say so, offer "try again", never "install anyway".
* Exit code 2 means *you* passed a bad option: log it as your bug, not the player's.
* Exit 1/101: show the last stderr line and the crash report path; offer to open the logs folder.
* Keep the last N builds (`policy.keepBuilds`) and let the player roll back.

## 6. Verification you must run before saying "done"

```sh
python3 -m porting.horizonport doctor
python3 -m porting.horizonport check --full
python3 -m unittest tests.test_horizonport_sign tests.test_horizonport_config \
                    tests.test_horizonport_fetch tests.test_horizonport_mods \
                    tests.test_horizonport_launch tests.test_horizonport_cli
node --check adapter/*.mjs        # if you ship the Node adapter
```

Plus the manual passes in [`CHECKLIST.md`](CHECKLIST.md): a signed-out Play, a non-owner account, a killed
download, a tampered archive, a full-disk prepare, and a second instance.

## 7. What not to do

* Do not vendor Mojang's files "so it works offline". It does not work; it is a licence violation.
* Do not add an "offline mode" login, a "skip signature" flag, or an "ignore owner gate" button.
* Do not shell out with tokens in argv, env or a world-readable file.
* Do not copy the engine's source into your launcher to save a download; install the signed build.
* Do not parse `logs/latest.log` to decide whether the game started; use the exit code and the crash line.
* Do not write your own `.hmod` packer that skips the checks; the game will refuse the file and the player
  will see "it doesn't load".
* Do not rename or move the toolkit's `store/`, `instances/` or `secrets/` folders without a migration.
* Do not commit `.horizonport/`, `dist/`, sessions or `*.hmod` build output.

## 8. Report format (for the agent to fill in)

```markdown
## HorizonPort port report
- Project: <path> (name, schema)
- Engine: <repo>@<tag> (commit), Launch API <version>, Minecraft <version>
- Build: verified <yes/no>, archive sha256 <…>, files <n>, bytes <n>
- Sign-in: <account name/uuid> (owns: yes/no), secrets mode 0600 <yes/no>
- Prepared: <store key>, <files>, <bytes>, reused on second run <yes/no>
- Instances: <name> → <build> (shares prepared tree: yes/no)
- Play: exit <code>, crash report <path or none>, options passed <list>
- Mods: <id> <version> installed/turned on <yes/no>
- Gates: <CHECKLIST item → pass/fail with evidence>
- Not done / blocked: <exact error, command, environment>
```

## 9. When a step fails

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| `fetch` says the signature doesn't match | key file wrong, tag wrong, or a tampered download | install nothing; retry; report a repeating mismatch |
| `fetch`: release has no `SHA256SUMS.sig` | a Nightly older than signing, or a build you made | install a signed release; for your own build pass `--allow-unsigned` deliberately |
| `prepare`: `horizon-prepare` exits 1 | no 26.3 install / wrong server jar / Java < 25 | `prepare --download`, `--server-jar`, `--java-home` |
| `prepare`: a file is not the one Mojang lists | a damaged or partial download | run it again; finished files are kept |
| `play`: exit 2 | an option the build doesn't take | ask `--launch-api`; use `play --dry-run` |
| `play`: exit 1/101 | the game crashed | read the crash report path printed last on stderr |
| `play`: online server refuses the player | no session, expired token, or non-owner | sign in again; `auth refresh` |
| `check`: prepared digest changed | a half-written or hand-edited tree | prepare again; investigate disk errors |
| `mod`: "would not load" | a path, manifest key or limit the engine refuses | fix the file; `mod check` names the reason |

## 10. The one-paragraph version

Make a port project, fetch a signature-verified Horizon build, sign the player in with your own Azure app,
prepare the resources once from the player's own game files, point every instance at that one prepared
folder, start the game with the Launch API's exact arguments and the session on stdin, manage `.hmod`
content mods in the game folder, and prove all of it with `check --full` plus the seven gates. Never ship,
log or bundle a Mojang file or a player's token.
