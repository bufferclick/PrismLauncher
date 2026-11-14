# Assets, downloaded once

The rule players feel: **the first Horizon instance downloads everything; every later one downloads
nothing.** This page is how that is true, what "everything" means, and what to do when it goes wrong.

## Three different things people call "assets"

| Layer | What it is | Made by | Size (26.3, desktop) | Where it lives |
| --- | --- | --- | --- | --- |
| 1. The build | `horizon-client`, `horizon-prepare`, `research-lock.json`, `exporters/` | Horizon's release CI | ~60–120 MB | `store/builds/<tag>/` |
| 2. The owner's game files | version JSON, client jar, libraries, asset index + objects, server jar | Mojang, downloaded for the owner | ~1 GB (assets ~500 MB, libraries ~150 MB, jars ~100 MB, server jar ~50 MB) | `store/mojang/<minecraft>/` |
| 3. Prepared resources | textures decoded, models baked, block/item facts, worldgen tables, data generator output, sounds | `horizon-prepare` from layer 2 | ~2–4 GB | `store/prepared/<key>/` |

Horizon contains **none** of layers 2 and 3. That is why a preparation exists at all
([`docs/native-client.md`](../docs/native-client.md)), and why the launcher — not the engine — fetches layer 2,
for an account that owns the game.

Layer 1 is the only thing a port may ship in a bundle: it is Horizon's own code, MIT-licensed and signed.

## The identity of a prepared tree

```text
key = "prepared:" + build_tag + "@" + minecraft + "@" + output_version
```

* **build_tag** — `store/builds/nightly`, say. A new build may change what the resources look like.
* **minecraft** — `26.3`. A different game version is different assets.
* **output_version** — the preparer's own layout number from `horizon-prepare --launch-api`
  (`output_version`, or `schema` on older builds). Two builds with the same layout still get separate trees,
  because the tag is in the key: a rollback must not be poisoned by a newer build's files.

Same key → the same folder → **every instance of that build points at one tree**. Different key → a new
folder, and the old one survives until no instance uses it.

## The sequence a port runs

```text
sign in (owner)                                    # once per account
  │
  ├─ adding instance #1 ─────────────────────────────────────────────────────┐
  │    fetch build      (network, ~1 min)                                    │
  │    mojang sync      (network, ~1 GB, resumable, checked per file)        │
  │    prepare          (CPU, minutes; Java 25; progress 0→1)                │
  │    link instance → prepared/<key>                                        │
  │                                                                          │
  ├─ adding instance #2..#N ─────────────────────────────────────────────────┤
  │    horizon-prepare --check → exit 0 → link (seconds, no network)         │
  │                                                                          │
  └─ updating the build ─────────────────────────────────────────────────────┘
       fetch new build   (network)
       check old tree    (fails for the new build's layout, or is absent)
       prepare new tree  (uses store/mojang — no game download)
       link instances to the new key
```

In commands:

```sh
horizonport fetch --tag nightly
horizonport prepare --download            # or --from-install ~/.minecraft
horizonport instance new Work             # links the tree; no work
horizonport instance new Second           # links the same tree; ~1 second
```

`horizonport prepare` on an already-current build prints `resources for <tag> are current` and returns; it
runs `horizon-prepare --check`, which reads no game files and no Java.

## Layout on disk

```text
<data>/
  store/
    builds/nightly/…                    layer 1, one folder per build
    mojang/26.3/
      versions/26.3/26.3.json
      versions/26.3/26.3.jar
      libraries/…                       Maven layout
      assets/indexes/26.3.json
      assets/objects/ab/<sha1>          content-addressed by Mojang's SHA-1
      server.jar
    prepared/prepared-nightly@26.3@7/   layer 3, one tree per key
    index.json                          digests, sizes, refs
    tmp/                                staging; nothing reaches its final name until complete
  instances/Work/{instance.json,game/,home/}
  secrets/<uuid>.json                   mode 0600
  accounts.json                         names and UUIDs only, never a token
```

Instances do not copy the tree: `--resources` points at the store. A 4 GB tree read by five instances is
4 GB on disk, not 20. That is also why removing an instance never removes a tree another one uses
(`store.references()`), and why `store gc` keeps every tree an instance points at.

If a launcher *does* want per-instance copies (some do, for sandboxing), `util.link_or_copy` hardlinks when
the filesystem allows it and falls back to copying. The digest lets it verify either way.

## Why not ship a prepared tree?

1. **Legal.** Layer 3 is derived from Mojang's assets; it is exactly as redistributable as the assets
   themselves (not at all). Horizon's own rule is that prepared resources never enter Git.
2. **Size.** A bundle with one prepared tree is gigabytes per platform and per game version.
3. **Accounts.** A download for the player's own account is the only version of this that Mojang's terms and
   Horizon's owner gate support.

A port may cache a tree **on the player's machine** forever. That is the whole point of the store.

## Integrity

| What | Check | When |
| --- | --- | --- |
| Build archive | Ed25519 signature over `horizon release <tag>\n` + `SHA256SUMS`, then the archive's SHA-256 | install |
| Game files | size + SHA-1 from Mojang's own version JSON, per file | download, and on resume |
| Prepared tree | `horizon-prepare --check` (the engine's own, fast) | before every start |
| Prepared tree | content digest in `store/index.json` | `store verify`, `check --full`, release |
| Instance | referenced build and tree exist | `check` |

`--check` is the cheap, authoritative one: it is the engine saying "these resources are complete and current
for *me*". The digest is for detecting drift (a half-written copy, a synced folder, a failing disk) and for
proving a release bundle matches what you tested.

## Failure cases, and what to do

| Situation | Behaviour | Player-visible |
| --- | --- | --- |
| Download interrupted | finished files are kept; the next run resumes | "Resuming: 812 of 1,203 files already in place" |
| Disk full during prepare | staging is removed; nothing marked current | "Not enough space: needs ~4 GB, 1.2 GB free" |
| Prepared tree edited by hand | `--check` fails; prepare again | "Repairing the game files (a few minutes)" |
| Two instances start at once | the engine's own lock (`--check` is read-only; one preparation writes) | nothing; the second waits |
| Data folder moved | entries are stored relative to the data folder | a "Move" setting that rewrites nothing |
| New build, old tree | a new key; the old tree stays while an instance uses it | "This build needs new resources; the last build still plays" |
| Cross-filesystem hardlink | falls back to a copy | slower first link, same result |
| Player switches Microsoft account | the tree is per build, not per account; no re-download | instant |

## Sizes to tell the player

Say them before the progress bar, so nobody thinks the launcher hung:

> First run: about 1 GB of Minecraft files and 2–4 GB of prepared resources. This happens once for this
> build. Later instances are instant, and updating to a new Horizon build does not download the game again.

Measure your own numbers with `horizonport store list` (per-entry `bytes`) and put them in your UI rather
than trusting this page.

## The rule in one sentence

Download the build (signed), download the game (once, for its owner), prepare the resources (once per build
and game version), point every instance at that one prepared folder, and never copy Mojang's content into
Git, a bundle or another machine.
