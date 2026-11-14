# Mods in a port

Horizon has three kinds of content, and only two of them are a launcher's business. Getting this table right
saves a port weeks.

| Kind | File | What it is | Built by | Launcher's job |
| --- | --- | --- | --- | --- |
| **Content mod** | `.hmod` | zip: `horizon-mod.toml` + `assets/` + `data/`, no code | anyone; `horizonport mod build` or `cargo horizon-mod` | install into `horizon-mods/`, toggle in `horizon-mods.txt` |
| **Native mod** | `.hnmod` | Rust sources built **into** the game | the launcher, with a Rust toolchain and a rebuild | only if you ship a native build pipeline; most ports don't |
| **Java mod** | `.jar` | Fabric/NeoForge/Forge code | mod authors | does not run; its data/assets can be carried over by the modpack porter |

Plus three pack formats that are not mods: resource packs (`resourcepacks/`), data packs
(`saves/<world>/datapacks/`), shader packs (`shaderpacks/`). Paths and toggles:
[`docs/api/content.md`](../docs/api/content.md).

## Content mods, the whole story

### Where they go

```text
<instance>/game/
  horizon-mods/<id>.hmod          or a folder holding horizon-mod.toml
  horizon-mods.txt                mod.<id>:true / mod.<id>:false
```

That is it. The game reads the folder at start; a mod with no line in `horizon-mods.txt` is **off**. The
game's own Options → Mods writes the same file, so your UI and the game always agree — as long as you edit
the file and not a copy of it.

### Inside the file

```text
horizon-mod.toml
assets/<namespace>/…            models, textures, lang
data/<namespace>/…              recipes, loot, tags, worldgen, horizon/ blocks and items
```

Manifest (unknown keys are refused, on purpose):

```toml
id = "ruby_mod"            # [a-z0-9_]{1,64}: folder, log and settings key
name = "Ruby Mod"
version = "0.1.0"
description = "A ruby block."
authors = ["You"]
api = "0.2"                # content mods
side = "both"              # client | server | both (see below)
capabilities = ["registries"]
namespaces = []            # extra namespaces the files use
```

A block is a declaration over a vanilla template (`docs/mods.md` has the full vocabulary: states,
`random_ticks`, `state_light`, `render_shape`, `occludes`, signs, and so on):

```json
{ "template": "minecraft:stone", "properties": { "hardness": 1.5 }, "item": true }
```

### `side` matters more than it looks

* `client` (the default when the line is absent): HUDs, minimaps — never sent to a server.
* `server`: rules and blocks that only the server simulates.
* `both`: the server tells clients which version it expects over `horizon:mod_list`; a client with a
  different version is refused with the mods named.

A content mod that adds blocks or items and should work on a server **must** say `side = "both"` and list
`registries`. Otherwise the check silently ignores it and players get "missing content".

### Limits the engine enforces (and the builder applies)

| What | Limit |
| --- | --- |
| A registry file | 64 MiB |
| Content files | 65,536 files, 16 MiB each, 512 MiB total |
| Path characters | lowercase `[a-z0-9_.-]`, at least `<assets\|data>/<namespace>/<folder>/<file>` |
| Top-level entries | only `horizon-mod.toml`, `assets/`, `data/` |

## Build, check, install, toggle

```sh
horizonport mod new ruby-mod                     # manifest + a block + a model + a lang file
horizonport mod build ruby-mod                   # target/horizon-mod/ruby_mod.hmod (deterministic)
horizonport mod check ruby-mod/target/horizon-mod/ruby_mod.hmod
horizonport mod install ruby-mod/target/horizon-mod/ruby_mod.hmod --instance Work
horizonport mod list --instance Work
horizonport mod disable ruby_mod --instance Work
```

`mod build` writes a fixed timestamp and mode into the zip, so two builds of the same files are
**byte-identical** — which is what makes a SHA-256 in a registry meaningful. `mod check` applies the same
rules the game does before the file reaches a game folder, so "it doesn't load" never reaches a player.

The engine's own tool does the same job and is the reference:

```sh
cargo horizon-mod new my-mod
cargo horizon-mod build
cargo horizon-mod run            # build and start the game with it
```

## Native mods: read this before promising them

A native mod is Rust code compiled into the game (`docs/native-mods.md`). The engine's launcher does it by
keeping a Rust toolchain, patching the pinned sources and rebuilding `horizon-client` — minutes per build,
hundreds of megabytes of toolchain, and a build that is **no longer the signed release**.

A port that installs signed builds therefore does **not** offer native mods. Say so plainly in the UI:
"Native mods need a custom build of Horizon; this launcher installs the official signed build." If you do
ship a native pipeline, it must be opt-in, clearly marked as an unsigned local build, and it must not replace
the signed build a player already has.

## Packs, briefly

| Pack | Goes in | Turned on by |
| --- | --- | --- |
| Resource pack | `resourcepacks/` (zip or folder with `pack.mcmeta`) | `options.txt`: `resourcePacks:["vanilla","file/<name>"]` |
| Data pack | `saves/<world>/datapacks/` | that world's `datapacks.json` (`enabled` / `disabled`) |
| Shader pack (Iris/OptiFine `shaders/`) | `shaderpacks/` | `horizon-graphics.txt`: `pickedShaderPack:<name>` |
| Shader pack (Horizon `.hshader`) | `shaderpacks/` | same key; needs a build whose `content.shader` lists its schema/api |

Install-after-checksum, format checks and "applies at next start" behaviour are all in
[`docs/api/content.md`](../docs/api/content.md). A port that offers packs should offer the same checks the mod
installer does: size, SHA-256, the format range from `--launch-api`.

## Java mods and modpacks

Horizon has no Java, so a Fabric/NeoForge/Forge jar cannot run. What a port can offer:

* **Explain it.** A "Java mods don't run in Horizon" line on the mod browser, with a link to what does.
* **Carry the data over.** The engine's `horizon-port-pack` (used by `horizon-launcher modpack import/port`)
  reads a jar's `assets/` and `data/`, rewrites 1.21-era folders and recipes to 26.3, and writes a content
  mod — then reports per mod what ported and what did not. From the CLI:
  `horizon-launcher modpack import <file>`, then `modpack port`, then `modpack play`.
* **Import packs**: `.mrpack`, CurseForge zips, Prism/MultiMC instances. The coverage report is honest per
  mod (ported / partial / not yet / not needed).

A small port can skip all of this and link to `horizon-launcher`. A port that offers it should surface the
coverage report rather than a green checkmark.

## Updates

* A mod file's identity is its SHA-256; keep it beside the file (your database or a sidecar) and never
  install a file whose hash doesn't match the listing you showed the player.
* Never update a mod while the game is running: content is read at start (a hot-reload path exists for
  assets-only mods, but a port should not rely on it).
* Keep the previous `.hmod` until the new one loads once, so "undo" is a file copy.

## The five mistakes ports make

1. Installing into `<game-dir>/mods/` (Java's folder) instead of `horizon-mods/`.
2. Writing `horizon-mods.txt` with a hand-rolled format (`ruby_mod=true`, JSON, etc.) — the game reads
   `mod.<id>:true` and nothing else.
3. Treating a mod folder as a zip (both work, but a folder needs `horizon-mod.toml` at its root).
4. Offering native mods from a signed-build launcher, then wondering why the signature no longer matches.
5. Saying "installed" before the file's SHA-256 matched the listing.
