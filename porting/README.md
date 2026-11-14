# The HorizonPort kit

Everything needed to put Horizon inside someone else's launcher. Start with
[`../PORTING.md`](../PORTING.md) if you are a person, or [`AGENT-GUIDE.md`](AGENT-GUIDE.md) if you are an AI
agent doing the work.

```sh
./porting/bin/horizonport guide        # the ten steps
./porting/bin/horizonport doctor       # is this machine ready?
./porting/bin/horizonport init ~/MyLauncher --name "My Launcher"
```

(From inside the repository, `python3 -m porting.horizonport …` is the same command; `porting/bin/horizonport`
works from any folder.)

## Documents

| File | Read it when |
| --- | --- |
| [`../PORTING.md`](../PORTING.md) | you are doing the port and want the whole path, with reasons |
| [`AGENT-GUIDE.md`](AGENT-GUIDE.md) | you are an AI agent, or you want to hand the work to one |
| [`CHECKLIST.md`](CHECKLIST.md) | you think you are done (you are probably at gate 4) |
| [`contract.md`](contract.md) | you need the tables: who does what, file formats, env vars, versions |
| [`assets.md`](assets.md) | you are implementing the download-once store, or it is using too much disk |
| [`auth.md`](auth.md) | you are wiring sign-in, or a player says "it says I don't own it" |
| [`launch.md`](launch.md) | you are wiring Play, crashes, quick play or offline |
| [`mods.md`](mods.md) | you are offering mods, packs or modpacks |
| [`faq.md`](faq.md) | the answer is a design decision, not a fact |
| [`../docs/api/`](../docs/api/README.md) | you want the engine's own contract documents |

## Code

| Path | What it is |
| --- | --- |
| `horizonport/` | the toolkit: CLI and library, Python 3.11+, standard library only |
| `horizonport/sign.py` | Ed25519 + Horizon's signed checksums, no dependencies |
| `horizonport/fetch.py` | verify, unpack and record a release build |
| `horizonport/mojang.py` | the owner's game files, from Mojang, once |
| `horizonport/prepare.py` | run `horizon-prepare` once per build and reuse it forever |
| `horizonport/launch.py` | the Launch API client: plan, spawn, exit codes |
| `horizonport/mods.py` | build, check, install and toggle `.hmod` content mods |
| `horizonport/store.py` | the content-addressed, download-once store |
| `horizonport/cli.py` | every command, `--json` everywhere |
| `templates/adapter-node/` | a working Node adapter: sign-in, setup, play, no dependencies |
| `templates/adapter-rust/` | the same for a Rust/Tauri launcher |
| `templates/adapter-python/` | the same for a Python launcher, or to call the toolkit without a shell |
| `schemas/` | JSON Schemas for every file a port writes |
| `bin/` | `horizonport` and `horizonport.cmd` launchers |

## Tests

```sh
python3 -m unittest tests.test_horizonport_sign tests.test_horizonport_config \
                    tests.test_horizonport_fetch tests.test_horizonport_mods \
                    tests.test_horizonport_launch tests.test_horizonport_cli
```

The suite covers the Ed25519 vectors, tampered archives, traversal attacks, the store's digests and GC, mod
building and toggles, the launch plan against a fake build, the sign-in flow with a fake transport, and the CLI
end to end. It never touches the network, a Microsoft account or a game file.

## The rules the kit enforces so you don't have to remember them

1. A build installs only from a valid signature, into its own folder, never over a working one.
2. Archives cannot write outside their folder.
3. Resources are prepared once per build and Minecraft version, and reused.
4. A `.hmod` is refused before install if the engine would refuse it.
5. No command prints, logs or passes a token on a command line.
6. No Mojang file, prepared tree or session is ever written into this repository or a bundle.

## Licence

MIT, like the engine ([`../LICENSE`](../LICENSE)). Minecraft is Mojang's; see the README's trademarks note.
