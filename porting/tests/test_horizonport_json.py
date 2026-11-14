"""`--json` has to mean exactly that.

A release shipped in which `horizonport fetch` succeeded and JL still refused
it with "printed something that is not JSON". The command was fine; stdout was
not. `info()` wrote progress to stdout, so the launcher received

    unpacking horizon-linux-x86_64.zip (399 B)
    {
      "tag": "v1",
      ...

and parsed the lot. The fix has two halves, and both are asserted here: the
toolkit keeps stdout to one object, and a caller can parse the whole buffer
rather than guessing which line holds the JSON.

The object is pretty-printed across many lines, so "take the last line" and
"take the line that starts with {" are both wrong for the same reason: the
object has no single line.
"""

import base64
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from porting.horizonport import cli, util
from porting.horizonport.config import PortProject
from porting.horizonport.store import Entry, Store, build_key
from porting.tests.test_horizonport_fetch import KEY, make_build_zip, signed_sums


def signed_archive(work: Path):
    archive = make_build_zip(work / "horizon-linux-x86_64.zip")
    sums, signature = signed_sums(archive, "v1", work)
    keys = work / "keys.txt"
    keys.write_text(base64.b64encode(KEY).decode() + "\n", encoding="utf-8")
    return archive, sums, signature, keys


class JsonContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        self.project = PortProject.create(self.work / "port", name="JL")
        self.archive, self.sums, self.signature, self.keys = signed_archive(self.work)

    def tearDown(self):
        # --json is a global switch; leaking it would silence later tests.
        util.set_json_mode(False)
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["--json", "--project", str(self.project.root), *argv])
        return code, out.getvalue(), err.getvalue()

    def test_fetch_prints_one_object_and_nothing_else(self):
        code, out, err = self.run_cli(
            "fetch", "--tag", "v1", "--archive", str(self.archive),
            "--sums", str(self.sums), "--signature", str(self.signature), "--keys", str(self.keys),
        )
        self.assertEqual(code, 0, err)
        # The whole of stdout parses. This is the assertion that was missing:
        # the old code checked the JSON existed, not that stdout was only JSON.
        payload = json.loads(out)
        self.assertEqual(payload["tag"], "v1")

    def test_progress_goes_to_stderr_in_json_mode(self):
        code, out, err = self.run_cli(
            "fetch", "--tag", "v1", "--archive", str(self.archive),
            "--sums", str(self.sums), "--signature", str(self.signature), "--keys", str(self.keys),
        )
        self.assertEqual(code, 0, err)
        self.assertIn("unpacking", err)
        self.assertNotIn("unpacking", out)

    def test_the_object_spans_many_lines(self):
        # Guards the parsing mistake directly: no single line is the object.
        code, out, _ = self.run_cli(
            "fetch", "--tag", "v1", "--archive", str(self.archive),
            "--sums", str(self.sums), "--signature", str(self.signature), "--keys", str(self.keys),
        )
        self.assertEqual(code, 0)
        self.assertGreater(len(out.strip().splitlines()), 1)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(out.strip().splitlines()[0])

    def test_instance_creation_is_parseable_too(self):
        # The command that failed for the player is fetch; prepare and play go
        # through the same path, so the contract is checked on a second command.
        build = self.project.builds / "nightly"
        build.mkdir(parents=True)
        (build / "horizon-client").write_text("x", encoding="utf-8")
        (build / "research-lock.json").write_text("{}", encoding="utf-8")
        code, out, err = self.run_cli("builds")
        self.assertEqual(code, 0, err)
        json.loads(out)


class HumanModeTests(unittest.TestCase):
    """Without --json the prose output, progress included, stays on stdout."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        self.project = PortProject.create(self.work / "port", name="JL")
        self.archive, self.sums, self.signature, self.keys = signed_archive(self.work)

    def tearDown(self):
        util.set_json_mode(False)
        self.tmp.cleanup()

    def test_a_person_still_sees_progress_on_stdout(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([
                "--project", str(self.project.root), "fetch", "--tag", "v1",
                "--archive", str(self.archive), "--sums", str(self.sums),
                "--signature", str(self.signature), "--keys", str(self.keys),
            ])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("unpacking", out.getvalue())


if __name__ == "__main__":
    unittest.main()
