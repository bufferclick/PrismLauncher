# The long answers

The README's FAQ answers everything in a sentence or two. These are the questions that deserve more, usually
because the answer is a design decision rather than a fact.

---

## "Is this legal? Do I need my own Azure app?"

Two separate questions, two separate answers.

**Assets.** Horizon ships no Minecraft code, textures, sounds or data. A player prepares those from their own
copy. That is the same model the engine itself documents (`docs/microsoft-account.md`, "Downloading the game
for an owner"), and it is why a port must not bundle a prepared tree, a game jar or an asset store. A launcher
may download Mojang's files **for an account that owns the game**, exactly as the official launcher does.

**Sign-in.** The device-code flow requires an Azure application, and Mojang must approve that application for
`login_with_xbox`. Your launcher must register its own: using Horizon's client ID (or another launcher's) is a
policy and security problem, and Mojang's review is per-application. Approval takes days to weeks and is the
longest lead time in a port, so start it on day one.

The MIT licence covers Horizon's own code. Minecraft is Mojang's; the EULA governs the game, not the
launcher's source.

---

## "Why can't I ship the prepared resources? It would make first run instant."

Because they are derived from Mojang's assets, byte for byte in places (textures, sounds, language files).
Redistributing them is redistributing the game's content. Three practical consequences follow, and all three
point the same way:

1. Legal: don't.
2. Size: a bundle per platform * per build * per game version is gigabytes, and it grows with every release.
3. Accounts: the only version of "download the game" that fits both the EULA and the owner gate is "for the
   player's own account".

What you *may* ship: the toolkit, your adapter, the pin (build tag, archive SHA-256, Minecraft version,
Launch API line), and schemas. That is exactly what `horizonport bundle` writes.

---

## "What must a player own, exactly?"

A Microsoft account with an entitlement named `game_minecraft` or `product_minecraft` from
`api.minecraftservices.com/entitlements/mcstore`. Game Pass counts. A profile (`/minecraft/profile`) must also
exist; an account that owns the game but never created a profile is a real, common case and needs its own
message.

The account that **plays** must be the account that owns it. Signing in account A (owner) to play as account B
is not allowed by the engine's policy, and a launcher that fakes it produces unverifiable sessions that online
servers reject anyway.

---

## "Why does the first instance take so long, and how do I make it faster?"

The work is: download the build (~1 min), download the game (~1 GB), run Mojang's exporters over it (minutes,
CPU-bound, Java 25), copy sounds (~380 MB). None of it is avoidable for a first run, and all of it is once.

How to make it *feel* fast:

* Run the Mojang download and the build install in parallel with the UI, and keep finished files on failure.
* On a machine that already has 26.3 from any launcher, use `prepare --from-install` instead of `--download`:
  it skips ~1 GB and goes straight to the exporters.
* Let `HORIZON_PREPARE_JOBS` use the cores (the toolkit sets it to min(8, cores)).
* Show the engine's own `{fraction}` and `{message}` events; do not invent a fake progress bar.
* Never re-prepare: `--check` before every start, prepare only when it says so.
* Do not run `store verify` (full digests) on the Play path.

---

## "Can two builds share a prepared tree?"

Only if their prepared layouts are identical **and** you change the key on purpose. The toolkit's key is
`prepared:<build>@<minecraft>@<output_version>`: the build tag is part of it, so by default every build gets
its own tree. That is deliberate:

* a rollback must not be poisoned by a newer build's files;
* a build that changes a baked format would silently break the old one;
* disk is cheap compared to "the game renders garbage after an update".

If you are certain two builds are layout-compatible (`horizon-prepare --launch-api` returns the same
`output_version` for both, and the engine's `--check` passes), you may point the second instance at the first
tree in `instance.json`. `horizonport check` will list it as fine; you own that decision.

---

## "Can I fork Horizon, rebrand it, and ship it?"

Yes — MIT permits it, and `docs/forking.md` describes the `horizon-extras` feature that builds the game without
Horizon's own extras. Three conditions a launcher should respect:

1. You cannot keep the name/marks in a way that implies it is *the* Horizon; brand your fork as yours.
2. A fork signs its own builds with its own key: put the public key in a file and point
   `port.config.json` → `keys` at it. Never ship Horizon's key as if it signed your binaries.
3. You still cannot sign in with Horizon's client ID; register your own.

---

## "How do I handle macOS Gatekeeper, Windows SmartScreen and Linux?"

* **macOS:** release builds are signed ad hoc, so the first start needs right-click → Open, or your launcher
  clears the quarantine attribute (`com.apple.quarantine`) on the build folder after verifying it. Notarising
  a third-party binary you did not build is not yours to do.
* **Windows:** an unsigned `horizon-client.exe` will eventually get a SmartScreen prompt. Sign your *launcher*;
  explain the game's prompt rather than disabling security features. The arm64 build is a separate archive.
* **Linux:** ship the AppImage/tar.gz of your launcher; the game needs Vulkan or OpenGL 3.3, X11 or Wayland, and
  the usual ALSA/libudev libraries. Steam Deck is x86-64 and works; expect the first-run preparation to be slow
  on a microSD.
* **musl/Alpine:** an optional musl build exists but is unverified for gameplay, and preparation needs a
  musl-compatible JDK 25. Don't offer it as the default.

---

## "Can a port offer servers, LAN and multiplayer?"

* **Joining** vanilla and Horizon servers works, online mode included, as long as you hand over a valid
  session. Nothing else to do.
* **LAN** works: the engine discovers and hosts LAN worlds.
* **Hosting a dedicated server** is `horizon-server` (its own binary in the same release, `install.sh`,
  `server.toml`, backups, a web panel — `docs/hosting.md`). A port can shell out to it exactly as
  `horizon-launcher` does. It is a second product surface; don't promise it until you support it.
* **Play with Friends** (invite codes, relay) is a Horizon extra that needs Horizon's own services. A plain
  port should not advertise it.

---

## "What happens if the player is offline?"

Three cases:

1. **Never signed in, no network:** no session, so no Play. The sign-in screen says why.
2. **Signed in before, no network now:** the last ownership answer stands. The game starts without a session:
   single player, LAN hosting and offline-mode servers work; online-mode servers refuse the player. The UI
   should say "playing offline" rather than pretending everything is normal.
3. **Signed in, token expired, network available:** refresh silently before launch. If the refresh token is
   revoked, ask the player to sign in again, with the reason.

Do not treat a network failure as "doesn't own": that would lock a legitimate owner out of their own worlds.

---

## "How do I update the port when Horizon updates?"

Horizon ships Nightlies; tags are `nightly` and `nightly-<date>` (kept seven days). A build update is a new
folder, never an in-place patch:

1. `horizonport fetch --tag nightly` — verified, unpacked, recorded.
2. Ask the new build `--launch-api`: if its `output_version` changed, it needs new resources.
3. `horizonport prepare` — uses the game files already in `store/mojang/`, so no re-download.
4. Move instances to the new tag when the player asks (or on next Play), keeping the old build for rollback.
5. If your adapter reads Launch API fields, tolerate unknown ones; that is the stability rule.

Pin a **specific** `nightly-<date>` in `port.config.json` for a release you ship, rather than `nightly`, so a
build you tested is the build your players get. Then update the pin deliberately.

---

## "How do I test a port on CI with no Minecraft account?"

Test everything that does not need an owner:

* `horizonport init`, `check`, `doctor` (allow Java/Rust warnings), `mod new/build/check/install`.
* The Ed25519 verifier against RFC 8032 vectors and against a synthetic signed archive with your own key
  (`tests/test_horizonport_fetch.py`).
* Archive extraction attacks (traversal, symlinks).
* The launch plan against a fake build whose `--launch-api` reply you write (`tests/test_horizonport_launch.py`).
* Sign-in with a fake transport: pending polls, non-owner, child account, session file mode 0600.

What you cannot test in CI: a real `horizon-prepare` run (needs the game files and Java 25), a real game
window, and a real owner. Run those on a dev machine before a release, and record them in the report
(`AGENT-GUIDE.md`, section 8).

---

## "CLI or library — which should my launcher use?"

* **CLI (`--json`)** if your launcher is in another language, runs out-of-process, or wants one implementation
  of signature checks and prep. It is also what an agent can drive.
* **Import `porting.horizonport`** if your launcher *is* Python, or you want to pass progress callbacks and
  cancels in-process.
* **Never re-implement** `sign.py`/`fetch.py`/`prepare.py`. A second implementation is a second set of bugs in
  the part where a bug means "installed a tampered binary".

Both paths use `port.config.json`, the same store and the same `instance.json`, so a launcher can migrate
between them.

---

## "What about analytics, crash uploads and telemetry?"

Off by default, and a port should keep it that way:

* `policy.telemetry` false means the engine's consent file says no and nothing is sent.
* If you add your own analytics, it must be opt-in, itemised, and revocable; say exactly what is sent and
  where. Never send a token, a session, a world name, a server address or a chat line.
* `horizonport check --support` writes a JSON bundle with no tokens and no worlds — that is the thing to ask a
  player for, not their data folder.

---

## "How much disk does a port use, and how do I clean up?"

Roughly: build 60–120 MB, game files ~1 GB, prepared tree 2–4 GB per build kept, instances = their worlds and
packs. Five instances of one build still use one tree.

* `horizonport store list` — every entry and its size.
* `horizonport store gc` — removes what no instance uses, keeps `policy.keepBuilds` newest builds for rollback
  and never touches the game files.
* Deleting an instance deletes its worlds: ask first, and say the size.
* Moving the data folder: move it whole (the store's paths are relative) and point `paths.data` at it.

---

## "What is the smallest possible port?"

A CLI wrapper: `horizonport doctor`, `fetch`, `prepare`, `instance new`, `play`, and a sign-in screen. No mod
browser, no servers, no packs, no news. That is a complete, legal, working port — and the four hundred lines in
`templates/adapter-node/` are exactly that. Everything else is your launcher being itself.

---

## "What if I disagree with a rule here?"

Open an issue on the toolkit, with the case. The rules that are **not** negotiable are the ones that keep
players safe and the project legal: verify signatures, gate on ownership, never ship Mojang content, never put
a token in argv or a log. Everything else — UI, features, storage layout, which mods you offer — is yours.
