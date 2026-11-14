# The seven gates

A port ships when all seven pass. `horizonport check --full` proves 1–4 and 6–7 mechanically; gate 5 and the
manual passes at the end need a human (or an agent with a screen) to look.

## 1. Config

- [ ] `port.config.json` parses, every key is known, `horizonport` is `1`.
- [ ] `engine.repo` and `engine.tag` name the build you ship.
- [ ] `minecraft` matches the build's `--launch-api` reply.
- [ ] `auth.clientId` is **your own** Azure app's client ID (never Horizon's, never another launcher's).
- [ ] `paths.data` points somewhere writable that is not inside a synced folder by accident.

## 2. Builds

- [ ] `store/builds/<tag>/` holds `horizon-client`, `horizon-prepare` and `research-lock.json`.
- [ ] The archive's SHA-256 matched the signed `SHA256SUMS`.
- [ ] `horizon-client --launch-api` answered, and its `options` are what your launcher uses.
- [ ] A build installed with the wrong key installs **nothing** (try it).
- [ ] You keep `policy.keepBuilds` builds for rollback.

## 3. Resources

- [ ] `store/prepared/<key>/` exists and the engine's own `--check` passes against it.
- [ ] The key covers build + Minecraft + layout, so a new build gets a new tree.
- [ ] `horizonport prepare` on an already-prepared build takes seconds and downloads nothing.
- [ ] Sounds are there (`--complete` ran), or you accept a silent game and say so in the UI.
- [ ] Two instances share one tree; deleting an instance never deletes a tree another one uses.

## 4. Instances

- [ ] `instance.json` names a build and a prepared key that exist.
- [ ] `game/` holds the worlds and options; `home/` holds logs and crash reports.
- [ ] `play --dry-run` lists only options the build's `--launch-api` lists.
- [ ] A second instance plays without any download.
- [ ] Deleting an instance asks first and says where the worlds were.

## 5. Content

- [ ] A `.hmod` built by your launcher passes `mod check` and appears in the game's Options → Mods.
- [ ] Turning it on/off in your launcher changes `horizon-mods.txt` and the game agrees.
- [ ] A mod that would not load is refused **before** it reaches the game folder, with the reason.
- [ ] Data packs, resource packs and shader packs go where [`docs/api/content.md`](../docs/api/content.md)
      says (if you offer them).

## 6. Adapter

- [ ] The file `adapter.entry` names exists and is what your launcher runs.
- [ ] Sign-in shows a code, opens the browser, and reports "owns / doesn't own" plainly.
- [ ] Exit codes 0, 1, 2 and 101 are handled as the Launch API describes.
- [ ] A crash shows the report path and a way to open the logs folder.
- [ ] The UI never blocks on a minutes-long preparation without progress and a cancel.

## 7. Policy

- [ ] `policy.requireSignature` is `true` in the build a player runs.
- [ ] `policy.ownerGate` is `true`; there is no bypass flag, environment variable or hidden button.
- [ ] `policy.telemetry` is `false` unless the player opted in on a screen that explains what is sent.
- [ ] Tokens: stdin or a 0600 file; never argv, never a log, never a world-readable file.
- [ ] Your support bundle contains no token, no session and no world data.

---

# Manual passes (do these once per release)

| # | Do this | Expect |
| --- | --- | --- |
| 1 | Press Play while signed out | the sign-in screen, not a crash, not a silent nothing |
| 2 | Sign in with an account that does **not** own the game | Play refuses with the owner message; no download starts |
| 3 | Kill the network in the middle of `fetch` | nothing installed; running it again finishes |
| 4 | Kill the app in the middle of `prepare` | the tree is not current; running again reuses finished exporters |
| 5 | Hand-edit one file in a prepared tree, then Play | the engine's `--check` notices and the launcher prepares again |
| 6 | Replace a build archive with a modified one | the signature/checksum refuses it; the old build still plays |
| 7 | Fill the disk until `prepare` fails | a plain-language error, no half-written tree marked current |
| 8 | Add a second instance and press Play | starts in seconds; no download; the first instance still works |
| 9 | Remove the newest build while an instance plays it | the launcher refuses or migrates the instance, says which |
| 10 | Play a world, crash it on purpose (`/kill @s` in a hardcore world is not enough: use a corrupted pack) | the crash report path is shown and opens |
| 11 | Join an online-mode server | the player's own name and skin appear |
| 12 | Turn on a content mod, restart, break the block | the block exists, drops its loot, and survives a save/reload |
| 13 | Unplug the network after sign-in, then Play | the last ownership answer stands and the game starts offline |
| 14 | `horizonport check --full` on the shipped project | exit 0, no `FAIL` |
| 15 | `horizonport bundle`, then inspect it | `SHA256SUMS` verifies; no jar, no asset, no session, no world |

# Release checklist

- [ ] Version bumped (`horizonport` contract still 1, or a migration written).
- [ ] `port.config.json` pins the exact build tag you ship.
- [ ] `horizonport-bundle.json` records that build's `archiveSha256`.
- [ ] Changelog says what changed for players, not only for developers.
- [ ] Support page names the log folder, the crash-report folder and the support bundle command.
- [ ] Rollback tested: the previous build still plays.
