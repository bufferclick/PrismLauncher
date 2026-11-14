import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from porting.horizonport import auth, launch
from porting.horizonport import instance as instance_mod
from porting.horizonport.config import PortProject
from porting.horizonport.store import Entry, Store, build_key, prepared_key
from porting.horizonport.util import PortError

OPTIONS = [
    {"name": "--resources", "value": "DIR"},
    {"name": "--game-dir", "value": "DIR"},
    {"name": "--home", "value": "DIR"},
    {"name": "--width", "value": "N"},
    {"name": "--height", "value": "N"},
    {"name": "--fullscreen", "value": None},
    {"name": "--session-stdin", "value": None},
    {"name": "--quickPlaySingleplayer", "value": "WORLD"},
]


def make_playable(project, *, options=OPTIONS):
    build_dir = project.builds / "nightly"
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "horizon-client").write_text("not a real program", encoding="utf-8")
    store = Store(project)
    store.put(
        Entry(
            key=build_key("nightly"),
            kind="build",
            path="",
            extra={
                "launchApi": {
                    "launch_api": "0.1.0",
                    "minecraft": "26.3",
                    "java_major": 25,
                    "options": options,
                }
            },
        ),
        directory=build_dir,
    )
    prepared = project.prepared / "tree"
    prepared.mkdir(parents=True, exist_ok=True)
    (prepared / "assets.txt").write_text("prepared", encoding="utf-8")
    tree = store.put(
        Entry(key=prepared_key("nightly", "26.3", 7), kind="prepared", path="", extra={"build": "nightly"}),
        directory=prepared,
    )
    return instance_mod.create(project, "Work", build="nightly", prepared=tree.key)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = PortProject.create(Path(self.tmp.name) / "port")
        self.instance = make_playable(self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_command_is_the_launch_api_one(self):
        plan = launch.plan(self.project, self.instance)
        argv = plan.argv
        self.assertEqual(Path(argv[0]).name, "horizon-client")
        self.assertIn("--resources", argv)
        self.assertIn(str(self.project.prepared / "tree"), argv)
        self.assertIn("--game-dir", argv)
        self.assertIn(str(self.instance.game), argv)
        self.assertIn("--session-stdin", argv)
        self.assertEqual(argv[argv.index("--width") + 1], "1280")
        self.assertEqual(plan.cwd, str(self.project.builds / "nightly"))

    def test_instance_settings_win_over_the_defaults(self):
        self.instance.settings.update({"width": 1920, "height": 1080, "fullscreen": True})
        self.instance.save()
        argv = launch.plan(self.project, self.instance).argv
        self.assertEqual(argv[argv.index("--width") + 1], "1920")
        self.assertEqual(argv[argv.index("--height") + 1], "1080")
        self.assertIn("--fullscreen", argv)

    def test_a_world_is_opened_through_the_listed_option(self):
        argv = launch.plan(self.project, self.instance, world="Survival").argv
        self.assertEqual(argv[argv.index("--quickPlaySingleplayer") + 1], "Survival")

    def test_a_world_may_not_be_a_path(self):
        with self.assertRaises(PortError):
            launch.plan(self.project, self.instance, world="../saves/Survival")

    def test_an_option_the_build_does_not_list_is_refused(self):
        with self.assertRaises(PortError) as caught:
            launch.plan(self.project, self.instance, extra=["--teleport"])
        self.assertIn("--teleport", caught.exception.message)

    def test_a_listed_option_passes_through(self):
        argv = launch.plan(self.project, self.instance, extra=["--fullscreen"]).argv
        self.assertEqual(argv.count("--fullscreen"), 1)

    def test_an_old_build_without_game_dir_is_refused(self):
        old = [option for option in OPTIONS if option["name"] != "--game-dir"]
        with tempfile.TemporaryDirectory() as other:
            project = PortProject.create(Path(other) / "port")
            instance = make_playable(project, options=old)
            with self.assertRaises(PortError) as caught:
                launch.plan(project, instance)
            self.assertIn("--game-dir", caught.exception.message)

    def test_a_missing_prepared_tree_is_named(self):
        store = Store(self.project)
        store.remove(self.instance.prepared_key)
        with self.assertRaises(PortError) as caught:
            launch.plan(self.project, self.instance)
        self.assertIn("prepared", caught.exception.message.lower())

    def test_the_plan_serialises_for_a_launcher(self):
        payload = launch.plan(self.project, self.instance).to_json()
        self.assertEqual(json.loads(json.dumps(payload))["instance"], "Work")
        self.assertIn("argv", payload)


class CrashTests(unittest.TestCase):
    def test_the_crash_report_path_is_the_last_one(self):
        stderr = (
            "Horizon: something\n"
            "Horizon: crash report saved to /tmp/a.txt\n"
            "more\n"
            "Horizon: crash report saved to /tmp/crash-reports/c.txt\n"
        )
        self.assertEqual(launch.crash_report(stderr), "/tmp/crash-reports/c.txt")

    def test_no_crash_report_is_none(self):
        self.assertIsNone(launch.crash_report("Horizon: just a log line\n"))

    def test_every_documented_exit_code_has_a_meaning(self):
        for code in (0, 1, 2, 101):
            self.assertIn(code, launch.EXIT_MEANINGS)
        self.assertIn("refused", launch.explain(2))


class FakeTransport(auth.HttpTransport):
    """The seven Microsoft calls, answered locally."""

    def __init__(self, *, owns=True, xerr=None, pending=1):
        self.owns = owns
        self.xerr = xerr
        self.pending = pending

    def device_code(self, client_id):
        return {
            "device_code": "device",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://www.microsoft.com/link",
            "expires_in": 900,
            "interval": 1,
        }

    def poll_token(self, client_id, device_code):
        if self.pending > 0:
            self.pending -= 1
            return 200, {"error": "authorization_pending"}
        return 200, {"access_token": "msa", "refresh_token": "refresh"}

    def xbl(self, microsoft_token):
        return {"Token": "xbl", "DisplayClaims": {"xui": [{"uhs": "uhs"}]}}

    def xsts(self, xbl_token):
        if self.xerr:
            return {"XErr": self.xerr}
        return {"Token": "xsts"}

    def minecraft(self, uhs, xsts_token):
        return {"access_token": "minecraft-token", "expires_in": 86400}

    def entitlements(self, access_token):
        return {"items": [{"name": "game_minecraft"}] if self.owns else []}

    def profile(self, access_token):
        return 200, {"id": "069a79f444e94726a5befca90e38aaf5", "name": "Alex", "xuid": "123"}


class SignInTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = PortProject.create(Path(self.tmp.name) / "port")

    def tearDown(self):
        self.tmp.cleanup()

    def sign_in(self, **options):
        ticks = iter(range(0, 10_000))

        def clock():
            return float(next(ticks))

        return auth.sign_in(
            "11111111-2222-3333-4444-555555555555",
            transport=FakeTransport(**options),
            sleep=lambda _seconds: None,
            clock=clock,
        )

    def test_the_flow_returns_a_session_for_an_owner(self):
        account = self.sign_in()
        self.assertEqual(account.name, "Alex")
        self.assertEqual(account.uuid, "069a79f444e94726a5befca90e38aaf5")
        self.assertTrue(account.owns)
        session = account.session()
        self.assertEqual(session["user_type"], "msa")
        self.assertEqual(session["access_token"], "minecraft-token")
        self.assertEqual(session["xuid"], "123")

    def test_an_account_without_the_game_is_refused(self):
        with self.assertRaises(PortError) as caught:
            self.sign_in(owns=False)
        self.assertIn("doesn't own", caught.exception.message)

    def test_a_child_account_gets_the_xbox_message(self):
        with self.assertRaises(PortError) as caught:
            self.sign_in(xerr=2148916238)
        self.assertIn("child account", caught.exception.message)

    def test_pending_polls_are_waited_out(self):
        account = self.sign_in(pending=3)
        self.assertEqual(account.name, "Alex")

    def test_no_client_id_is_refused_with_where_to_get_one(self):
        with self.assertRaises(PortError) as caught:
            auth.sign_in("")
        self.assertIn("Azure", caught.exception.hint)

    def test_the_session_file_is_private_and_readable_by_the_game(self):
        account = self.sign_in()
        path = self.project.data / "session.json"
        auth.write_session(path, account)
        if os.name != "nt":
            mode = stat.S_IMODE(path.stat().st_mode)
            self.assertEqual(mode, 0o600)
        self.assertEqual(auth.read_session(path)["name"], "Alex")

    def test_stored_accounts_keep_no_token_in_the_index(self):
        account = self.sign_in()
        auth.save_account(self.project, account)
        index = json.loads((self.project.data / "accounts.json").read_text(encoding="utf-8"))
        self.assertEqual(index["accounts"][0]["name"], "Alex")
        self.assertNotIn("access_token", json.dumps(index))
        self.assertNotIn("refresh_token", json.dumps(index))
        secrets = json.loads((self.project.secrets / f"{account.uuid}.json").read_text(encoding="utf-8"))
        self.assertEqual(secrets["refresh_token"], "refresh")


if __name__ == "__main__":
    unittest.main()
