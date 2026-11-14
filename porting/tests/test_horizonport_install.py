"""The toolkit as it is actually shipped and started.

A release once went out in which every Horizon command failed with
``No module named 'porting'``. The file was in the archive, the archive was in
the zip, and the packaging check passed: it only asked whether the file existed.
Nobody asked whether it could be *run*.

The launcher starts the toolkit as ``python -m porting.horizonport`` with the
import root on PYTHONPATH. That only works when the root is the folder
*containing* ``porting/``; pointing it at ``porting/`` itself produces exactly
that import error. These tests hold that contract against a copy of the toolkit
laid out the way a shipped build lays it out.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
PACKAGE = KIT / "horizonport"

# What `python -m porting.horizonport` needs to be able to import.
REQUIRED = ("__init__.py", "horizonport/__init__.py", "horizonport/__main__.py", "horizonport/cli.py")


def shipped_copy(destination: Path) -> Path:
    """A copy of the toolkit in the layout a release ships: <dir>/porting/..."""
    shutil.copytree(
        KIT,
        destination / "porting",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "tests"),
    )
    return destination


class ShippedLayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = shipped_copy(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def run_toolkit(self, *args, root=None):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(root if root is not None else self.app)
        env["PYTHONUNBUFFERED"] = "1"
        return subprocess.run(
            [sys.executable, "-m", "porting.horizonport", *args],
            cwd=str(root if root is not None else self.app),
            env=env,
            capture_output=True,
            text=True,
        )

    def test_the_package_holds_everything_the_launcher_imports(self):
        for relative in REQUIRED:
            self.assertTrue((self.app / "porting" / relative).is_file(), relative)

    def test_it_runs_from_the_layout_the_launcher_ships(self):
        result = self.run_toolkit("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("horizonport", result.stdout)

    def test_doctor_runs_from_the_shipped_layout(self):
        result = self.run_toolkit("doctor")
        # A build machine has no Java or Rust; doctor reports those as warnings.
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("release keys", result.stdout)

    def test_pointing_pythonpath_at_the_package_itself_fails(self):
        # The bug, pinned. The import root is the folder holding porting/, never
        # porting/ itself; this asserts the failure is real so the launcher's
        # search cannot quietly regress into it.
        result = self.run_toolkit("--version", root=self.app / "porting")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No module named 'porting'", result.stderr)

    def test_a_json_command_works_from_the_shipped_layout(self):
        project = Path(self.tmp.name) / "project"
        result = subprocess.run(
            [sys.executable, "-m", "porting.horizonport", "--json", "--project", str(project),
             "init", str(project), "--name", "JL", "--adapter", "none"],
            cwd=str(self.app),
            env={**os.environ, "PYTHONPATH": str(self.app), "PYTHONUNBUFFERED": "1"},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((project / "port.config.json").is_file())


if __name__ == "__main__":
    unittest.main()
