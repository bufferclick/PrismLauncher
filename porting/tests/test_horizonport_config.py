import json
import tempfile
import unittest
from pathlib import Path

from porting.horizonport import instance as instance_mod
from porting.horizonport.config import PortProject, merge_defaults
from porting.horizonport.store import Entry, Store, build_key, prepared_key
from porting.horizonport.util import PortError, digest_tree


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "port"
        self.project = PortProject.create(self.root, name="Test Launcher")

    def tearDown(self):
        self.tmp.cleanup()

    def test_defaults_describe_a_usable_port(self):
        self.assertEqual(self.project.problems(), [])
        self.assertEqual(self.project.minecraft, "26.3")
        self.assertTrue(self.project.policy["requireSignature"])
        self.assertTrue(self.project.policy["ownerGate"])
        self.assertFalse(self.project.policy["telemetry"])
        self.assertEqual(self.project.adapter_entry, self.root / "adapter" / "index.mjs")

    def test_data_lives_under_the_project_and_resolves(self):
        self.assertEqual(self.project.data, self.root / ".horizonport")
        self.assertEqual(self.project.store, self.root / ".horizonport" / "store")
        self.assertTrue(self.project.store.is_dir())

    def test_an_absolute_data_path_is_kept(self):
        outside = Path(self.tmp.name) / "elsewhere"
        self.project.config["paths"]["data"] = str(outside)
        self.assertEqual(self.project.data, outside)

    def test_unknown_keys_are_refused_not_ignored(self):
        self.project.config["policy"]["requireSignature!"] = True
        self.assertTrue(any("policy" in problem for problem in self.project.problems()))

    def test_a_bad_window_size_is_named(self):
        self.project.config["launch"]["width"] = 3
        problems = self.project.problems()
        self.assertTrue(any("launch.width" in problem for problem in problems), problems)

    def test_load_finds_the_project_from_a_subfolder(self):
        (self.root / "src" / "deep").mkdir(parents=True)
        loaded = PortProject.load(self.root / "src" / "deep")
        self.assertEqual(loaded.root, self.root.resolve())

    def test_load_without_a_project_says_how_to_make_one(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(PortError) as caught:
                PortProject.load(empty)
            self.assertIn("init", caught.exception.hint)

    def test_merge_defaults_fills_in_a_partial_file(self):
        merged = merge_defaults({"name": "X", "launch": {"width": 800}})
        self.assertEqual(merged["launch"]["width"], 800)
        self.assertEqual(merged["launch"]["height"], 720)
        self.assertEqual(merged["engine"]["repo"], "horizon-rust/horizon")

    def test_a_written_config_round_trips(self):
        self.project.save()
        again = PortProject.load(self.root)
        self.assertEqual(again.config, self.project.config)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = PortProject.create(Path(self.tmp.name) / "port")
        self.store = Store(self.project)

    def tearDown(self):
        self.tmp.cleanup()

    def make_build(self, tag="nightly", files=("horizon-client", "research-lock.json")):
        folder = self.project.builds / tag
        folder.mkdir(parents=True)
        for name in files:
            (folder / name).write_text("x", encoding="utf-8")
        return folder

    def test_an_entry_records_its_digest_and_files(self):
        folder = self.make_build()
        entry = self.store.put(Entry(key=build_key("nightly"), kind="build", path=""), directory=folder)
        self.assertEqual(entry.files, 2)
        self.assertEqual(len(entry.digest), 64)
        self.assertTrue((self.project.data / "store" / "index.json").is_file())

    def test_a_changed_entry_fails_verification(self):
        folder = self.make_build()
        entry = self.store.put(Entry(key=build_key("nightly"), kind="build", path=""), directory=folder)
        good, _ = self.store.verify(entry)
        self.assertTrue(good)
        (folder / "extra.txt").write_text("changed", encoding="utf-8")
        good, detail = self.store.verify(entry)
        self.assertFalse(good)
        self.assertIn("contents changed", detail)

    def test_a_missing_entry_fails_verification(self):
        folder = self.make_build()
        entry = self.store.put(Entry(key=build_key("nightly"), kind="build", path=""), directory=folder)
        (folder / "horizon-client").unlink()
        good, detail = self.store.verify(entry)
        self.assertFalse(good)

    def test_an_instance_keeps_its_build_and_tree(self):
        self.make_build()
        prepared = self.project.prepared / "tree"
        prepared.mkdir(parents=True)
        (prepared / "file").write_text("y", encoding="utf-8")
        build = self.store.put(Entry(key=build_key("nightly"), kind="build", path=""), directory=self.project.builds / "nightly")
        tree = self.store.put(Entry(key=prepared_key("nightly", "26.3", 7), kind="prepared", path=""), directory=prepared)
        instance_mod.create(self.project, "Work", build="nightly", prepared=tree.key)

        refs = self.store.references()
        self.assertIn("instance:Work", refs[build.key])
        self.assertIn("instance:Work", refs[tree.key])
        self.assertEqual(self.store.gc(dry_run=True), [])

    def test_gc_removes_only_unreferenced_entries(self):
        self.make_build()
        builder = self.store
        builder.put(Entry(key=build_key("nightly"), kind="build", path=""), directory=self.project.builds / "nightly")
        unused = self.project.prepared / "unused"
        unused.mkdir(parents=True)
        (unused / "f").write_text("z", encoding="utf-8")
        builder.put(Entry(key="prepared:unused", kind="prepared", path=""), directory=unused)
        removed = self.store.gc()
        self.assertEqual(removed, ["prepared:unused"])
        self.assertFalse(unused.exists())
        self.assertTrue((self.project.builds / "nightly").is_dir())

    def test_game_files_are_never_collected(self):
        folder = self.project.mojang / "26.3"
        folder.mkdir(parents=True)
        (folder / "server.jar").write_text("j", encoding="utf-8")
        self.store.put(Entry(key="mojang:26.3", kind="mojang", path=""), directory=folder)
        self.assertEqual(self.store.gc(), [])
        self.assertTrue(folder.is_dir())

    def test_tree_digest_ignores_nothing(self):
        root = Path(self.tmp.name) / "tree"
        root.mkdir()
        (root / "a").write_text("1", encoding="utf-8")
        first, files, size = digest_tree(root)
        self.assertEqual((files, size), (1, 1))
        (root / "b").write_text("2", encoding="utf-8")
        second, files, _ = digest_tree(root)
        self.assertNotEqual(first, second)
        self.assertEqual(files, 2)

    def test_the_index_is_json_and_sorted(self):
        self.make_build()
        self.store.put(Entry(key=build_key("nightly"), kind="build", path=""), directory=self.project.builds / "nightly")
        raw = json.loads((self.project.store / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["schema"], 1)
        self.assertEqual(list(raw["entries"]), ["build:nightly"])


if __name__ == "__main__":
    unittest.main()
