"""The `horizonport` command line: one verb per thing a port has to do.

Design rules, because a launcher developer's time is the scarce resource:

* every command says what it will do *before* it does it, and what changed after;
* a command that needs a project says how to make one, and one that needs a
  build says how to fetch it;
* `--json` prints one object, for a launcher's own UI or an agent;
* failures exit 1, refusals (bad arguments, missing project) exit 2, like the
  engine's own tools.
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from . import auth, bundle, check, doctor, fetch, guide, instance as instance_mod, launch, mods, prepare, scaffold, sign
from .config import CONFIG_NAME, PortProject
from .store import Store, build_key
from .util import PortError, error, human_bytes, info, ok, step, table, warn

VERSION = "1.0.0"
CONTRACT = 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return dispatch(args, parser)
    except PortError as exc:
        error(exc.message)
        if exc.hint:
            print(f"  {exc.hint}", file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
        return 130


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="horizonport",
        description="Port Horizon (Minecraft: Java Edition in Rust) into your own launcher.",
        epilog=(
            "Start with `horizonport doctor`, then read PORTING.md. "
            "Feed AGENT-GUIDE.md to an AI agent to have the whole port done for you."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", metavar="DIR", default=".", help="the port project (default: here or above)")
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of prose")
    parser.add_argument("--version", action="version", version=f"horizonport {VERSION} (contract {CONTRACT})")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    sub.add_parser("guide", help="print the ten steps, and where each doc is")
    sub.add_parser("docs", help="where the handbook, the agent guide and the checklist are")

    p = sub.add_parser("doctor", help="check this machine can build and run a port")
    p.add_argument("--full", action="store_true", help="also hash every store entry (slow)")

    p = sub.add_parser("init", help="make a port project (config, adapter, schemas, docs)")
    p.add_argument("dir", nargs="?", default=".", metavar="DIR")
    p.add_argument("--name", help="the launcher's name, as players see it")
    p.add_argument("--adapter", choices=("node", "rust", "python", "none"), default="node")
    p.add_argument("--force", action="store_true", help="write into a folder that already has a config")

    p = sub.add_parser("fetch", help="download, verify and install a Horizon build")
    p.add_argument("--tag", help="the release tag (default: engine.tag in port.config.json)")
    p.add_argument("--archive", type=Path, help="a local archive instead of a download")
    p.add_argument("--sums", type=Path, help="a local SHA256SUMS for --archive")
    p.add_argument("--signature", type=Path, help="the SHA256SUMS signature (SHA256SUMS.sig)")
    p.add_argument("--signature-for", metavar="VERSION", help="what the signature covers, for Nightly's v2 signature")
    p.add_argument("--allow-unsigned", action="store_true", help="install a build you made yourself (loudly)")
    p.add_argument("--keys", type=Path, help="a key file to trust instead of Horizon's")
    p.add_argument("--repo", help="owner/repository to fetch from (default: engine.repo)")

    p = sub.add_parser("builds", help="list or remove installed builds")
    b = p.add_subparsers(dest="builds_command", metavar="ACTION")
    b.add_parser("list", help="the installed builds")
    r = b.add_parser("remove", help="remove an installed build")
    r.add_argument("tag")

    p = sub.add_parser("prepare", help="prepare resources once per build (minutes)")
    p.add_argument("--build", help="the build to prepare (default: engine.tag)")
    p.add_argument("--from-install", type=Path, metavar="DIR", help="a Minecraft game folder (official launcher, Prism, MultiMC...)")
    p.add_argument("--prism-dir", type=Path, help="a Prism/MultiMC root or instance to read as is")
    p.add_argument("--server-jar", type=Path, help="the pinned server jar (first preparation only)")
    p.add_argument("--java-home", type=Path, help="a Java of the pinned version your launcher manages")
    p.add_argument("--download", action="store_true", help="download the game files from Mojang for a signed-in owner")
    p.add_argument("--session", type=Path, help="the session JSON of the owner (with --download)")
    p.add_argument("--force", action="store_true", help="prepare again even when the tree is current")
    p.add_argument("--plan", action="store_true", help="say what preparing needs, and stop")

    p = sub.add_parser("instance", help="make, list, inspect and remove instances")
    i = p.add_subparsers(dest="instance_command", metavar="ACTION")
    n = i.add_parser("new", help="make an instance and attach a build")
    n.add_argument("name")
    n.add_argument("--build", help="the build to play (default: engine.tag)")
    n.add_argument("--width", type=int)
    n.add_argument("--height", type=int)
    n.add_argument("--fullscreen", action="store_true")
    n.add_argument("--no-prepare", action="store_true", help="attach without preparing resources first")
    i.add_parser("list", help="the instances here")
    f = i.add_parser("info", help="one instance in detail")
    f.add_argument("name")
    d = i.add_parser("remove", help="delete an instance and its folders")
    d.add_argument("name")
    d.add_argument("--yes", action="store_true", help="do not ask")
    pl = i.add_parser("play", help="same as `horizonport play NAME`")
    pl.add_argument("name")

    p = sub.add_parser("play", help="start the game for an instance")
    p.add_argument("instance")
    p.add_argument("--dry-run", action="store_true", help="print the exact command and exit")
    p.add_argument("--session", type=Path, help="a session JSON instead of the stored account")
    p.add_argument("--offline", action="store_true", help="start without a session (testing only)")
    p.add_argument("--world", help="open this world of saves/ at once")
    p.add_argument("--server", help="join this server at once")
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--arg", action="append", default=[], dest="extra", metavar="ARG", help="an extra game argument (repeatable)")

    p = sub.add_parser("auth", help="Microsoft sign-in and sessions")
    a = p.add_subparsers(dest="auth_command", metavar="ACTION")
    s = a.add_parser("sign-in", help="device-code sign-in for an account that owns the game")
    s.add_argument("--client-id", help="your Azure app's Application (client) ID")
    s.add_argument("--no-browser", action="store_true", help="only print the code")
    s.add_argument("--session-out", type=Path, help="also write the session JSON here (0600)")
    a.add_parser("accounts", help="the accounts signed in here")
    rf = a.add_parser("refresh", help="renew the stored account's token")
    rf.add_argument("account", nargs="?")
    se = a.add_parser("session", help="write the stored account's session JSON (0600)")
    se.add_argument("--account", help="name or UUID (default: the first)")
    se.add_argument("--out", type=Path, help="where to write it (default: <data>/session.json)")

    p = sub.add_parser("mod", help="content mods: scaffold, build, check, install")
    m = p.add_subparsers(dest="mod_command", metavar="ACTION")
    mn = m.add_parser("new", help="scaffold a content mod")
    mn.add_argument("path", type=Path)
    mn.add_argument("--name")
    mn.add_argument("--id", dest="mod_id")
    mb = m.add_parser("build", help="build <id>.hmod (validated, deterministic)")
    mb.add_argument("path", type=Path)
    mb.add_argument("--out", type=Path, help="the .hmod to write")
    mc = m.add_parser("check", help="check a .hmod the way the game would")
    mc.add_argument("file", type=Path)
    mi = m.add_parser("install", help="install a .hmod into an instance")
    mi.add_argument("file", type=Path)
    mi.add_argument("--instance", required=True)
    mi.add_argument("--disabled", action="store_true", help="install turned off")
    ml = m.add_parser("list", help="the mods in an instance")
    ml.add_argument("--instance", required=True)
    me = m.add_parser("enable", help="turn a mod on")
    me.add_argument("mod_id")
    me.add_argument("--instance", required=True)
    md = m.add_parser("disable", help="turn a mod off (it stays installed)")
    md.add_argument("mod_id")
    md.add_argument("--instance", required=True)

    p = sub.add_parser("store", help="the download-once store")
    st = p.add_subparsers(dest="store_command", metavar="ACTION")
    st.add_parser("list", help="every entry, with its size")
    sv = st.add_parser("verify", help="re-hash entries and compare with the index")
    sv.add_argument("--quick", action="store_true", help="count files instead of hashing them")
    sv.add_argument("--key", help="only this entry")
    sg = st.add_parser("gc", help="remove entries no instance uses")
    sg.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("assets", help="what an instance's first run downloads")
    at = p.add_subparsers(dest="assets_command", metavar="ACTION")
    ap = at.add_parser("plan", help="say what is downloaded once and what is reused")
    ap.add_argument("--build", help="the build to describe (default: engine.tag)")

    p = sub.add_parser("check", help="the seven gates: would this port work for a player?")
    p.add_argument("--full", action="store_true", help="hash every store entry too")
    p.add_argument("--support", type=Path, metavar="DIR", help="write a support bundle (no tokens) to DIR")

    p = sub.add_parser("bundle", help="write the distributable port bundle")
    p.add_argument("--out", type=Path, metavar="DIR")

    return parser


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
def dispatch(args, parser) -> int:
    command = args.command
    if command in (None,):
        parser.print_help()
        return 0
    if command == "guide":
        print(guide.render())
        return 0
    if command == "docs":
        return _docs(args)
    if command == "doctor":
        return _doctor(args)
    if command == "init":
        return _init(args)
    if command == "fetch":
        return _fetch(args)
    if command == "builds":
        return _builds(args)
    if command == "prepare":
        return _prepare(args)
    if command == "instance":
        return _instance(args)
    if command == "play":
        return _play(args)
    if command == "auth":
        return _auth(args)
    if command == "mod":
        return _mod(args)
    if command == "store":
        return _store(args)
    if command == "assets":
        return _assets(args)
    if command == "check":
        return _check(args)
    if command == "bundle":
        return _bundle(args)
    parser.error(f"unknown command {command!r}")
    return 2


def _project(args, *, required: bool = True) -> PortProject:
    return PortProject.load(args.project, required=required)


def _emit(args, payload: dict, prose: str | None = None) -> int:
    if args.json:
        print(json.dumps(payload, indent=2))
    elif prose:
        print(prose)
    return 0


def _docs(args) -> int:
    rows = []
    for name in guide.DOCS:
        path = guide.path_for(name)
        rows.append((name, str(path) if path else "missing", "in the kit"))
    if args.json:
        print(json.dumps({name: str(guide.path_for(name)) for name in guide.DOCS}, indent=2))
    else:
        table(rows, headers=("doc", "file", "what"))
        print("\n`horizonport guide` prints the ten steps.")
    return 0


def _doctor(args) -> int:
    project: PortProject | None
    try:
        project = _project(args)
    except PortError:
        project = None
        if not args.json:
            warn("no port project here (run `horizonport init`); checking the machine only")
    rows = doctor.collect(project, full=args.full)
    if args.json:
        print(json.dumps([{"status": a, "what": b, "detail": c} for a, b, c in rows], indent=2))
        return 1 if any(row[0] == doctor.FAIL for row in rows) else 0
    return doctor.render(rows)


def _init(args) -> int:
    project = scaffold.init(Path(args.dir), name=args.name, adapter=args.adapter, force=args.force)
    steps = [
        f"cd {project.root}",
        "horizonport doctor",
        "horizonport fetch",
        "horizonport prepare --download     # or --from-install PATH",
        "horizonport instance new Work",
        "horizonport play Work",
    ]
    if args.json:
        return _emit(args, {"root": str(project.root), "config": project.describe(), "next": steps})
    ok(f"port project ready at {project.root}")
    print("\nNext, in this order:")
    for index, command in enumerate(steps, 1):
        print(f"  {index}. {command}")
    print("\nThe handbook is PORTING.md; hand AGENT-GUIDE.md to an AI agent to do the rest.")
    return 0


def _fetch(args) -> int:
    project = _project(args)
    tag = args.tag or project.engine["tag"] or "nightly"
    if args.allow_unsigned and project.policy.get("requireSignature"):
        warn("installing without a signature while policy.requireSignature is true (development only)")
    keys = None
    if args.keys:
        if not args.keys.is_file():
            raise PortError(f"{args.keys} does not exist")
        keys = sign.parse_keys(args.keys.read_text(encoding="utf-8"))
    entry = fetch.install(
        project,
        tag,
        archive=args.archive,
        sums_file=args.sums,
        signature_file=args.signature,
        signature_for=args.signature_for,
        allow_unsigned=args.allow_unsigned,
        keys=keys,
        repo=args.repo,
    )
    store = Store(project)
    api = entry.extra.get("launchApi") or {}
    payload = {
        "tag": tag,
        "path": str(store.entry_path(entry)),
        "files": entry.files,
        "bytes": entry.bytes,
        "digest": entry.digest,
        "archiveSha256": entry.extra.get("archiveSha256"),
        "launchApi": api.get("launch_api"),
        "minecraft": api.get("minecraft"),
    }
    if args.json:
        return _emit(args, payload)
    ok(f"{tag} installed: {entry.files} files, {human_bytes(entry.bytes)}")
    if api:
        print(f"  Launch API {api.get('launch_api')}, Minecraft {api.get('minecraft')}, Java {api.get('java_major')}")
    print(f"  {store.entry_path(entry)}")
    print("\nNext: horizonport prepare" + (" (--download, or --from-install PATH)"))
    return 0


def _builds(args) -> int:
    project = _project(args)
    store = Store(project)
    action = args.builds_command or "list"
    if action == "list":
        entries = store.builds()
        if args.json:
            return _emit(args, {"builds": [
                {"tag": e.key.split(":", 1)[1], "path": str(store.entry_path(e)), "files": e.files, "bytes": e.bytes}
                for e in entries
            ]})
        if not entries:
            info("no builds installed yet: horizonport fetch")
            return 0
        table(
            [("build", e.key.split(":", 1)[1], f"{human_bytes(e.bytes)}, {e.files} files") for e in entries],
            headers=("kind", "tag", "size"),
        )
        return 0
    tag = args.tag
    if not store.find(build_key(tag)):
        raise PortError(f"{tag} is not installed")
    if args.json:
        store.remove(build_key(tag))
        return _emit(args, {"removed": tag})
    store.remove(build_key(tag))
    ok(f"removed {tag} (prepared trees stay until `horizonport store gc`)")
    return 0


def _prepare(args) -> int:
    project = _project(args)
    store = Store(project)
    tag = args.build or project.engine["tag"] or (store.builds()[0].key.split(":", 1)[1] if store.builds() else "nightly")
    if args.plan:
        rows = prepare.describe(project, tag)
        if args.json:
            return _emit(args, {"build": tag, "needs": [{"what": a, "value": b, "detail": c} for a, b, c in rows]})
        table(rows, headers=("what", "value", "detail"))
        return 0

    session = None
    if args.download:
        if args.session:
            session = auth.read_session(args.session)
        else:
            account = auth.load_account(project)
            if not account.owns and project.policy.get("ownerGate", True):
                raise PortError(
                    "the signed-in account doesn't own Minecraft: Java Edition",
                    hint="Sign in with the account that owns the game, or prepare --from-install PATH.",
                )
            session = account.session()

    entry, folder = prepare.ensure(
        project,
        tag,
        minecraft_dir=args.from_install,
        prism_dir=args.prism_dir,
        server_jar=args.server_jar,
        java_home=args.java_home,
        download=args.download,
        session=session,
        force=args.force,
    )
    payload = {
        "build": tag,
        "prepared": entry.key,
        "path": str(folder),
        "files": entry.files,
        "bytes": entry.bytes,
        "digest": entry.digest,
    }
    if args.json:
        return _emit(args, payload)
    ok(f"resources ready for {tag}: {entry.files} files, {human_bytes(entry.bytes)}")
    print(f"  {folder}")
    print("\nEvery instance of this build reuses this folder: adding one costs a --check, not a download.")
    return 0


def _ensure_prepared(project, tag: str, args) -> tuple[object, Path]:
    store = Store(project)
    build = store.find(build_key(tag))
    if build is None:
        raise PortError(
            f"{tag} is not installed",
            hint=f"Run `horizonport fetch --tag {tag}` first.",
        )
    try:
        return prepare.ensure(project, tag)
    except PortError as exc:
        raise PortError(
            exc.message,
            hint=(exc.hint or "") + "\n  Choose the game files once:\n"
            "    horizonport prepare --download            (a signed-in owner; downloads from Mojang once)\n"
            "    horizonport prepare --from-install PATH   (your own 26.3 install)\n"
            "  or pass --no-prepare and attach resources later.",
        ) from None


def _instance(args) -> int:
    project = _project(args)
    action = args.instance_command or "list"
    if action == "new":
        return _instance_new(project, args)
    if action == "list":
        summaries = instance_mod.summaries(project)
        if args.json:
            return _emit(args, {"instances": summaries})
        if not summaries:
            info("no instances yet: horizonport instance new Work")
            return 0
        table(
            [
                (item["name"], item.get("build", "-"), f"{item.get('playCount', 0)} play(s), {item.get('mods', 0)} mod(s)")
                for item in summaries
                if "error" not in item
            ],
            headers=("instance", "build", "state"),
        )
        return 0
    if action == "info":
        instance = instance_mod.load(project, args.name)
        payload = dict(instance.describe())
        payload["worlds"] = instance_mod.open_worlds(instance)
        payload["modList"] = instance.mods()
        if args.json:
            return _emit(args, payload)
        for key, value in payload.items():
            print(f"{key:<10} {value}")
        return 0
    if action == "remove":
        instance = instance_mod.load(project, args.name)
        if not args.yes and not args.json:
            answer = input(f"Delete {instance.name} and its worlds in {instance.folder}? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                info("nothing removed")
                return 0
        folder = instance_mod.remove(project, instance.name)
        if args.json:
            return _emit(args, {"removed": str(folder)})
        ok(f"removed {folder}")
        return 0
    if action == "play":
        return _play_with(project, args.name, args)
    raise PortError(f"unknown instance action {action!r}")


def _instance_new(project, args) -> int:
    store = Store(project)
    tag = args.build or project.engine["tag"] or "nightly"
    if not store.find(build_key(tag)):
        if args.no_prepare:
            raise PortError(
                f"{tag} is not installed",
                hint=f"Run `horizonport fetch --tag {tag}` first.",
            )
        step(1, f"installing {tag}")
        fetch.install(project, tag)
    prepared = None
    if not args.no_prepare:
        existing = [entry for entry in store.prepared() if entry.extra.get("build") == tag]
        if existing:
            step(2, f"reusing the prepared resources from {existing[0].key}")
            prepared = existing[0].key
        else:
            step(2, f"preparing {tag} (the one slow step)")
            entry, _folder = _ensure_prepared(project, tag, args)
            prepared = entry.key
    settings = {}
    if args.width:
        settings["width"] = args.width
    if args.height:
        settings["height"] = args.height
    if args.fullscreen:
        settings["fullscreen"] = True
    instance = instance_mod.create(
        project,
        args.name,
        build=tag,
        prepared=prepared or "",
        settings=settings,
    )
    payload = instance.describe()
    if args.json:
        return _emit(args, payload)
    ok(f"instance {instance.name} is ready at {instance.folder}")
    if prepared:
        print(f"  shares {prepared} with every other instance of {tag}")
    print(f"\nPlay it: horizonport play {instance.name}")
    return 0


def _play(args) -> int:
    project = _project(args)
    return _play_with(project, args.instance, args)


def _play_with(project, name: str, args) -> int:
    instance = instance_mod.load(project, name)
    if getattr(args, "dry_run", False):
        plan = launch.plan(
            project,
            instance,
            width=getattr(args, "width", None),
            height=getattr(args, "height", None),
            fullscreen=getattr(args, "fullscreen", None),
            world=getattr(args, "world", None),
            server=getattr(args, "server", None),
            extra=getattr(args, "extra", None),
        )
        payload = plan.to_json()
        if args.json:
            return _emit(args, payload)
        print(json.dumps(payload, indent=2))
        return 0
    code = launch.play(
        project,
        instance,
        session_path=getattr(args, "session", None),
        width=getattr(args, "width", None),
        height=getattr(args, "height", None),
        fullscreen=getattr(args, "fullscreen", None),
        world=getattr(args, "world", None),
        server=getattr(args, "server", None),
        extra=getattr(args, "extra", None),
        allow_offline=getattr(args, "offline", False),
    )
    if args.json:
        _emit(args, {"instance": instance.name, "exit": code, "meaning": launch.explain(code)})
        return code
    info(f"exit {code}: {launch.explain(code)}")
    return code


def _auth(args) -> int:
    project = _project(args)
    action = args.auth_command or "accounts"
    if action == "sign-in":
        client_id = args.client_id or project.client_id
        if not client_id:
            raise PortError(
                "no Microsoft client ID",
                hint="Register an Azure app (porting/auth.md), then pass --client-id or set auth.clientId.",
            )

        def show(uri: str, code: str, expires: float) -> None:
            print(f"\n  Open {uri} and enter: {code}\n  (the code expires in {int(expires // 60)} minutes)\n")
            if not args.no_browser:
                try:
                    webbrowser.open(uri)
                except Exception:
                    pass

        account = auth.sign_in(client_id, on_code=show)
        path = auth.save_account(project, account)
        if args.session_out:
            auth.write_session(args.session_out, account)
        payload = {
            "name": account.name,
            "uuid": account.uuid,
            "owns": account.owns,
            "secrets": str(path),
            "session": str(args.session_out) if args.session_out else None,
        }
        if args.json:
            return _emit(args, payload)
        ok(f"signed in as {account.name} ({account.uuid}); owns Minecraft: Java Edition")
        print("The game starts only for an owner; that is policy.ownerGate.")
        return 0
    if action == "accounts":
        index = project.data / "accounts.json"
        accounts = []
        if index.is_file():
            accounts = json.loads(index.read_text(encoding="utf-8")).get("accounts", [])
        if args.json:
            return _emit(args, {"accounts": accounts})
        if not accounts:
            info("no accounts yet: horizonport auth sign-in --client-id <GUID>")
            return 0
        table(
            [(item.get("name", "?"), item.get("uuid", "?"), "owner" if item.get("owns") else "no ownership")]
            for item in accounts
        )
        return 0
    if action == "refresh":
        client_id = project.client_id
        if not client_id:
            raise PortError("no Microsoft client ID in port.config.json (auth.clientId)")
        account = auth.load_account(project, args.account)
        renewed = auth.refresh(account, client_id)
        auth.save_account(project, renewed)
        if args.json:
            return _emit(args, {"name": renewed.name, "owns": renewed.owns})
        ok(f"renewed the sign-in for {renewed.name}")
        return 0
    if action == "session":
        account = auth.load_account(project, getattr(args, "account", None))
        out = args.out or (project.data / "session.json")
        auth.write_session(out, account)
        if args.json:
            return _emit(args, {"session": str(out), "name": account.name})
        ok(f"session for {account.name} written to {out} (mode 600)")
        return 0
    raise PortError(f"unknown auth action {action!r}")


def _mod(args) -> int:
    project = _project(args)
    action = args.mod_command
    if action == "new":
        path = mods.new(args.path, name=args.name, mod_id=args.mod_id)
        if args.json:
            return _emit(args, {"path": str(path)})
        ok(f"content mod scaffolded at {path}")
        print(f"  build it: horizonport mod build {path}")
        return 0
    if action == "build":
        report = mods.build(args.path, output=args.out)
        if args.json:
            return _emit(args, report)
        ok(f"{report['mod']} {report['version']}: {report['file']} ({human_bytes(report['size'])})")
        print(f"  sha256 {report['sha256']}")
        return 0
    if action == "check":
        report = mods.check(args.file)
        if args.json:
            return _emit(args, report)
        ok(f"{report['mod']} {report['version']} ({report['side']}): {report['entries']} entries, {human_bytes(report['bytes'])}")
        return 0
    if action == "install":
        instance = instance_mod.load(project, args.instance)
        report = mods.install(project, instance, args.file, enable=not args.disabled)
        if args.json:
            return _emit(args, report)
        ok(f"installed {report['mod']} {report['version']} into {instance.name}")
        state = "off" if args.disabled else "on"
        print(f"  {report['installed']} (turned {state}; applies when the game starts)")
        return 0
    if action == "list":
        instance = instance_mod.load(project, args.instance)
        rows = mods.installed(instance)
        if args.json:
            return _emit(args, {"instance": instance.name, "mods": rows})
        if not rows:
            info(f"{instance.name} has no content mods")
            return 0
        table(
            [
                ("on" if row.get("enabled") else "off", row.get("mod", row["file"]), row.get("version", row.get("error", "")))
                for row in rows
            ],
            headers=("state", "mod", "version"),
        )
        return 0
    if action in ("enable", "disable"):
        instance = instance_mod.load(project, args.instance)
        path = mods.set_enabled(instance, args.mod_id, action == "enable")
        if args.json:
            return _emit(args, {"instance": instance.name, "mod": args.mod_id, "enabled": action == "enable"})
        ok(f"{args.mod_id} turned {'on' if action == 'enable' else 'off'} ({path})")
        return 0
    raise PortError(f"unknown mod action {action!r}")


def _store(args) -> int:
    project = _project(args)
    store = Store(project)
    action = args.store_command or "list"
    if action == "list":
        rows = store.summarise()
        if args.json:
            return _emit(args, {"entries": [
                {"key": key, "kind": store.entries[key].kind, "bytes": store.entries[key].bytes,
                 "files": store.entries[key].files, "path": str(store.entry_path(store.entries[key]))}
                for key in sorted(store.entries)
            ], "bytes": store.total_bytes()})
        if not rows:
            info("the store is empty: horizonport fetch")
            return 0
        table(rows, headers=("kind", "key", "size"))
        print(f"\n{human_bytes(store.total_bytes())} in the store")
        return 0
    if action == "verify":
        entries = [store.entries[args.key]] if args.key else list(store.entries.values())
        if args.key and args.key not in store.entries:
            raise PortError(f"the store has no {args.key}")
        failures = 0
        rows = []
        for entry in entries:
            good, detail = store.verify(entry, full=not args.quick)
            rows.append(("ok" if good else "CHANGED", entry.key, detail))
            failures += 0 if good else 1
        if args.json:
            return _emit(args, {"failures": failures, "entries": [
                {"status": a, "key": b, "detail": c} for a, b, c in rows
            ]})
        for status, key, detail in rows:
            print(f"{status:<8} {key:<32} {detail}")
        return 1 if failures else 0
    if action == "gc":
        removed = store.gc(dry_run=args.dry_run)
        if args.json:
            return _emit(args, {"removed": removed, "dryRun": args.dry_run})
        if not removed:
            info("nothing to collect: every entry is used by an instance")
        else:
            verb = "would remove" if args.dry_run else "removed"
            for key in removed:
                print(f"  {verb} {key}")
        return 0
    raise PortError(f"unknown store action {action!r}")


def _assets(args) -> int:
    project = _project(args)
    store = Store(project)
    tag = args.build or project.engine["tag"] or "nightly"
    build = store.find(build_key(tag))
    api = build.extra.get("launchApi") if build else None
    rows = [
        ("once", "Horizon build", f"{tag}: one signed archive, kept in the store"),
        ("once", f"Minecraft {project.minecraft}", "version file, client jar, libraries, assets and the server jar"),
        ("once", "prepared resources", "horizon-prepare's output for this build and game version"),
        ("never again", "every later instance", "a --check (seconds), linking the same prepared folder"),
        (
            "per update",
            "the new build and its prepared tree",
            "the owner's game files are reused, and the old build stays for rollback",
        ),
    ]
    if api:
        rows.insert(0, ("info", "Launch API", f"{api.get('launch_api')} for {api.get('minecraft')}, Java {api.get('java_major')}"))
    mojang_entry = store.find(f"mojang:{project.minecraft}")
    if mojang_entry:
        rows.append(("have", "game files", f"{human_bytes(mojang_entry.bytes)} already downloaded"))
    if args.json:
        return _emit(args, {"rows": [{"when": a, "what": b, "detail": c} for a, b, c in rows]})
    table(rows, headers=("when", "what", "detail"))
    return 0


def _check(args) -> int:
    project = _project(args)
    if args.support:
        path = check.support_bundle(project, args.support)
        if args.json:
            return _emit(args, {"support": str(path)})
        ok(f"support bundle written to {path} (no tokens, no worlds)")
        return 0
    rows = check.run(project, full=args.full)
    if args.json:
        print(json.dumps([{"status": a, "what": b, "detail": c} for a, b, c in rows], indent=2))
        return 1 if any(row[0] == check.FAIL for row in rows) else 0
    return check.render(rows)


def _bundle(args) -> int:
    project = _project(args)
    path = bundle.build(project, out=args.out)
    if args.json:
        return _emit(args, {"bundle": str(path)})
    ok(f"bundle written to {path}")
    print("  horizonport-bundle.json, adapter/, schemas/, AGENT-GUIDE.md, SHA256SUMS")
    print("  no game files, no prepared resources, no sessions")
    return 0
