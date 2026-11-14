import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from porting.horizonport import cli
from porting.horizonport.config import PortProject
from porting.tests.test_horizonport_launch import make_playable


def run(*argv):
    """Run the CLI, returning (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "launcher"

    def tearDown(self):
        self.tmp.cleanup()

    def init(self):
        code, out, _ = run("init", str(self.root), "--name", "Demo Launcher")
        self.assertEqual(code, 0, out)
        return PortProject.load(self.root)

    def test_init_writes_a_project_a_launcher_can_use(self):
        project = self.init()
        self.assertTrue((self.root / "port.config.json").is_file())
        self.assertTrue((self.root / "adapter" / "index.mjs").is_file())
        self.assertTrue((self.root / "schemas" / "instance.schema.json").is_file())
        self.assertTrue((self.root / ".gitignore").is_file())
        self.assertEqual(project.config["name"], "Demo Launcher")

    def test_init_copies_the_documents_the_kit_promises(self):
        self.init()
        for name in ("AGENT-GUIDE.md", "CHECKLIST.md", "README.md"):
            path = self.root / name
            self.assertTrue(path.is_file(), name)
            self.assertGreater(len(path.read_text(encoding="utf-8")), 500, name)

    def test_init_twice_is_refused_unless_forced(self):
        self.init()
        code, _, err = run("init", str(self.root))
        self.assertEqual(code, 2, err)
        self.assertIn("already exists", err)
        code, out, _ = run("init", str(self.root), "--force")
        self.assertEqual(code, 0, out)
        self.assertEqual(PortProject.load(self.root).config["name"], "Demo Launcher")

    def test_init_can_copy_the_python_adapter(self):
        code, out, _ = run("init", str(self.root), "--name", "Py", "--adapter", "python")
        self.assertEqual(code, 0, out)
        adapter = self.root / "adapter" / "adapter.py"
        self.assertTrue(adapter.is_file())
        self.assertIn("class HorizonPort", adapter.read_text(encoding="utf-8"))

    def test_check_reports_the_gates_and_passes(self):
        self.init()
        code, out, _ = run("--json", "--project", str(self.root), "check")
        self.assertEqual(code, 0, out)
        rows = json.loads(out)
        self.assertTrue(any(row["what"] == "config" for row in rows))
        self.assertFalse([row for row in rows if row["status"] == "FAIL"], rows)

    def test_doctor_prints_json_rows(self):
        self.init()
        code, out, _ = run("--json", "--project", str(self.root), "doctor")
        self.assertIn(code, (0, 1))
        rows = json.loads(out)
        self.assertTrue(any(row["what"] == "python >= 3.11" for row in rows))

    def test_guide_and_docs_run(self):
        code, out, _ = run("guide")
        self.assertEqual(code, 0)
        self.assertIn("ten steps", out)
        code, out, _ = run("--json", "docs")
        self.assertEqual(code, 0)
        self.assertIn("handbook", json.loads(out))

    def test_a_missing_archive_fails_with_a_message_not_a_traceback(self):
        self.init()
        code, out, err = run("--project", str(self.root), "fetch", "--archive", str(self.root / "nope.zip"))
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err)

    def test_a_project_is_required_for_project_commands(self):
        code, _, err = run("--project", str(Path(self.tmp.name) / "empty"), "check")
        self.assertEqual(code, 2)
        self.assertIn("init", err)


class InstanceAndModTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = PortProject.create(Path(self.tmp.name) / "port", name="Demo")
        self.instance = make_playable(self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def test_instances_are_listed_with_their_build(self):
        code, out, _ = run("--json", "--project", str(self.project.root), "instance", "list")
        self.assertEqual(code, 0)
        entries = json.loads(out)["instances"]
        self.assertEqual(entries[0]["name"], "Work")
        self.assertEqual(entries[0]["build"], "nightly")

    def test_a_new_instance_reuses_the_prepared_tree(self):
        code, out, _ = run("--project", str(self.project.root), "instance", "new", "Second")
        self.assertEqual(code, 0, out)
        second = json.loads((self.project.instances / "Second" / "instance.json").read_text(encoding="utf-8"))
        first = json.loads((self.project.instances / "Work" / "instance.json").read_text(encoding="utf-8"))
        self.assertEqual(second["prepared"], first["prepared"])

    def test_a_mod_is_built_checked_and_installed_from_the_cli(self):
        mod_root = Path(self.tmp.name) / "ruby"
        self.assertEqual(run("--project", str(self.project.root), "mod", "new", str(mod_root))[0], 0)
        code, out, _ = run("--json", "--project", str(self.project.root), "mod", "build", str(mod_root))
        self.assertEqual(code, 0, out)
        built = json.loads(out)["file"]
        self.assertEqual(run("--project", str(self.project.root), "mod", "check", built)[0], 0)
        code, out, _ = run(
            "--json", "--project", str(self.project.root), "mod", "install", built, "--instance", "Work"
        )
        self.assertEqual(code, 0, out)
        self.assertTrue((self.instance.game / "horizon-mods" / "ruby.hmod").is_file())
        code, out, _ = run("--json", "--project", str(self.project.root), "mod", "list", "--instance", "Work")
        rows = json.loads(out)["mods"]
        self.assertEqual(rows[0]["mod"], "ruby")
        self.assertTrue(rows[0]["enabled"])

    def test_play_dry_run_prints_the_command(self):
        code, out, _ = run("--json", "--project", str(self.project.root), "play", "Work", "--dry-run")
        self.assertEqual(code, 0, out)
        plan = json.loads(out)
        self.assertEqual(plan["instance"], "Work")
        self.assertIn("--session-stdin", plan["argv"])

    def test_assets_explains_the_download_once_rule(self):
        code, out, _ = run("--json", "--project", str(self.project.root), "assets", "plan")
        self.assertEqual(code, 0)
        rows = json.loads(out)["rows"]
        self.assertTrue(any(row["when"] == "once" for row in rows))
        self.assertTrue(any(row["what"] == "every later instance" for row in rows))


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = PortProject.create(Path(self.tmp.name) / "port", name="Demo")
        make_playable(self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_bundle_pins_the_build_and_carries_no_game_files(self):
        code, out, _ = run("--json", "--project", str(self.project.root), "bundle")
        self.assertEqual(code, 0, out)
        bundle = Path(json.loads(out)["bundle"])
        manifest = json.loads((bundle / "horizonport-bundle.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "Demo")
        self.assertEqual(manifest["builds"][0]["tag"], "nightly")
        self.assertIn("no game files", manifest["contents"])
        self.assertTrue((bundle / "SHA256SUMS").is_file())
        self.assertTrue((bundle / "horizonport-bundle.json").is_file())
        names = {path.name for path in bundle.rglob("*")}
        self.assertNotIn("horizon-client", names)


if __name__ == "__main__":
    unittest.main()
