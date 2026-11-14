import tempfile
import unittest
import zipfile
from pathlib import Path

from porting.horizonport import instance as instance_mod
from porting.horizonport import mods
from porting.horizonport.config import PortProject
from porting.horizonport.util import PortError


class ScaffoldAndBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_writes_a_manifest_and_content(self):
        folder = mods.new(self.work / "ruby", name="Ruby")
        self.assertTrue((folder / "horizon-mod.toml").is_file())
        self.assertTrue((folder / "data" / "ruby" / "horizon" / "block" / "example_block.json").is_file())
        report = mods.build(folder)
        self.assertEqual(report["mod"], "ruby")
        self.assertTrue(Path(report["file"]).is_file())

    def test_build_is_deterministic(self):
        folder = mods.new(self.work / "diamond", name="Diamond")
        first = mods.build(folder)
        again = mods.build(folder)
        self.assertEqual(first["sha256"], again["sha256"], "two builds of the same files must be identical")

    def test_check_reads_what_build_wrote(self):
        folder = mods.new(self.work / "emerald", name="Emerald")
        report = mods.build(folder)
        checked = mods.check(Path(report["file"]))
        self.assertEqual(checked["mod"], "emerald")
        self.assertEqual(checked["api"], "0.2")
        self.assertEqual(checked["side"], "both")
        self.assertEqual(checked["sha256"], report["sha256"])

    def test_an_unknown_manifest_key_is_refused(self):
        folder = mods.new(self.work / "badkey")
        manifest = folder / "horizon-mod.toml"
        manifest.write_text(manifest.read_text() + "\ncode = true\n", encoding="utf-8")
        with self.assertRaises(PortError) as caught:
            mods.build(folder)
        self.assertIn("unknown key", caught.exception.message)

    def test_an_uppercase_content_path_is_refused(self):
        folder = mods.new(self.work / "upper")
        (folder / "data" / "upper" / "recipe").mkdir(parents=True)
        (folder / "data" / "upper" / "recipe" / "Bad.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(PortError) as caught:
            mods.build(folder)
        self.assertIn("lowercase", caught.exception.message)

    def test_a_file_outside_assets_and_data_is_refused(self):
        problems = mods.content_problems("src/main.rs")
        self.assertTrue(any("assets/ and data/" in problem for problem in problems), problems)
        self.assertEqual(mods.content_problems("assets/outside/lang/en_us.json"), [])
        self.assertTrue(mods.content_problems("assets/outside/en_us.json"), "a file needs a folder of its own")

    def test_check_refuses_a_zip_that_is_not_a_mod(self):
        plain = self.work / "plain.hmod"
        with zipfile.ZipFile(plain, "w") as archive:
            archive.writestr("readme.txt", "hi")
        with self.assertRaises(PortError):
            mods.check(plain)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = PortProject.create(Path(self.tmp.name) / "port")
        self.instance = instance_mod.create(
            self.project, "Work", build="nightly", prepared="prepared:nightly@26.3@1"
        )
        source = mods.new(Path(self.tmp.name) / "ruby", name="Ruby")
        self.hmod = Path(mods.build(source)["file"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_install_copies_the_file_and_turns_it_on(self):
        report = mods.install(self.project, self.instance, self.hmod)
        installed = self.instance.game / "horizon-mods" / "ruby.hmod"
        self.assertTrue(installed.is_file())
        self.assertEqual(report["mod"], "ruby")
        self.assertTrue(mods.enabled_map(self.instance)["ruby"])

    def test_install_can_leave_it_off(self):
        mods.install(self.project, self.instance, self.hmod, enable=False)
        self.assertFalse(mods.enabled_map(self.instance).get("ruby", False))

    def test_enable_and_disable_edit_the_same_file_the_game_reads(self):
        mods.install(self.project, self.instance, self.hmod)
        mods.set_enabled(self.instance, "ruby", False)
        text = (self.instance.game / "horizon-mods.txt").read_text(encoding="utf-8")
        self.assertIn("mod.ruby:false", text)
        mods.set_enabled(self.instance, "ruby", True)
        text = (self.instance.game / "horizon-mods.txt").read_text(encoding="utf-8")
        self.assertIn("mod.ruby:true", text)
        self.assertEqual(text.count("mod.ruby:"), 1, "one line per mod, never two")

    def test_installed_lists_what_the_folder_holds(self):
        mods.install(self.project, self.instance, self.hmod)
        rows = mods.installed(self.instance)
        self.assertEqual([row["mod"] for row in rows], ["ruby"])
        self.assertTrue(rows[0]["enabled"])

    def test_the_instance_remembers_its_mods(self):
        mods.install(self.project, self.instance, self.hmod)
        again = instance_mod.load(self.project, "Work")
        self.assertEqual([mod["id"] for mod in again.mods()], ["ruby"])


if __name__ == "__main__":
    unittest.main()
