import base64
import hashlib
import io
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from porting.horizonport import fetch, sign
from porting.horizonport.config import PortProject
from porting.horizonport.store import Store
from porting.horizonport.util import PortError
from porting.tests.test_horizonport_sign import ed25519_public_key, ed25519_sign

SEED = bytes(range(32))
KEY = ed25519_public_key(SEED)


def make_build_zip(path: Path, extra: dict[str, str] | None = None) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("horizon-client", "#!/bin/sh\nexit 0\n")
        archive.writestr("horizon-prepare", "#!/bin/sh\nexit 0\n")
        archive.writestr("research-lock.json", '{"minecraft": "26.3"}')
        for name, text in (extra or {}).items():
            archive.writestr(name, text)
    return path


def signed_sums(archive: Path, tag: str, work: Path) -> tuple[Path, Path]:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    sums = f"{digest}  {archive.name}\n".encode()
    signature = ed25519_sign(SEED, sign.message(tag, sums))
    sums_file = work / "SHA256SUMS"
    signature_file = work / "SHA256SUMS.sig"
    sums_file.write_bytes(sums)
    signature_file.write_text(base64.b64encode(signature).decode() + "\n", encoding="utf-8")
    return sums_file, signature_file


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        self.project = PortProject.create(self.work / "port")
        self.archive = make_build_zip(self.work / "horizon-linux-x86_64.zip")
        self.sums, self.signature = signed_sums(self.archive, "v1", self.work)

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, **overrides):
        options = dict(
            archive=self.archive,
            sums_file=self.sums,
            signature_file=self.signature,
            keys=[KEY],
        )
        options.update(overrides)
        return fetch.install(self.project, "v1", **options)

    def test_a_signed_build_installs_with_its_programs(self):
        entry = self.install()
        folder = Store(self.project).entry_path(entry)
        self.assertTrue((folder / "horizon-client").is_file())
        self.assertTrue((folder / "horizon-prepare").is_file())
        self.assertTrue((folder / "research-lock.json").is_file())
        self.assertEqual(entry.extra["archiveSha256"], hashlib.sha256(self.archive.read_bytes()).hexdigest())
        self.assertGreater(entry.files, 0)

    def test_the_wrong_key_installs_nothing(self):
        other = ed25519_public_key(bytes(range(1, 33)))
        with self.assertRaises(PortError):
            self.install(keys=[other])
        self.assertFalse((self.project.builds / "v1").exists())

    def test_a_changed_archive_installs_nothing(self):
        make_build_zip(self.archive, {"extra.txt": "changed after signing"})
        with self.assertRaises(PortError) as caught:
            self.install()
        self.assertIn("does not match", caught.exception.message)
        self.assertFalse((self.project.builds / "v1").exists())

    def test_an_unsigned_archive_is_refused_by_default(self):
        with self.assertRaises(PortError):
            fetch.install(self.project, "v1", archive=self.archive)
        self.assertFalse((self.project.builds / "v1").exists())

    def test_an_unsigned_archive_installs_only_when_asked(self):
        entry = fetch.install(self.project, "v1", archive=self.archive, allow_unsigned=True)
        self.assertTrue(Store(self.project).entry_path(entry).is_dir())

    def test_an_archive_without_the_programs_is_refused(self):
        plain = self.work / "plain.zip"
        with zipfile.ZipFile(plain, "w") as archive:
            archive.writestr("readme.txt", "not a build")
        sums, signature = signed_sums(plain, "v2", self.work)
        with self.assertRaises(PortError) as caught:
            fetch.install(
                self.project, "v2", archive=plain, sums_file=sums, signature_file=signature, keys=[KEY]
            )
        self.assertIn("horizon-client", caught.exception.message)
        self.assertFalse((self.project.builds / "v2").exists())

    def test_a_single_top_folder_is_flattened(self):
        nested = self.work / "nested.zip"
        with zipfile.ZipFile(nested, "w") as archive:
            archive.writestr("horizon/horizon-client", "x")
            archive.writestr("horizon/horizon-prepare", "x")
            archive.writestr("horizon/research-lock.json", "{}")
        sums, signature = signed_sums(nested, "v3", self.work)
        entry = fetch.install(
            self.project, "v3", archive=nested, sums_file=sums, signature_file=signature, keys=[KEY]
        )
        folder = Store(self.project).entry_path(entry)
        self.assertTrue((folder / "horizon-client").is_file())
        self.assertFalse((folder / "horizon").exists())


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_zip_entries_may_not_escape(self):
        hostile = self.work / "hostile.zip"
        with zipfile.ZipFile(hostile, "w") as archive:
            archive.writestr("../evil.txt", "no")
        with self.assertRaises(PortError):
            fetch.extract(hostile, self.work / "out")
        self.assertFalse((self.work / "evil.txt").exists())

    def test_tar_symlinks_are_refused(self):
        hostile = self.work / "hostile.tar.gz"
        with tarfile.open(hostile, "w:gz") as archive:
            info = tarfile.TarInfo("link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            archive.addfile(info, io.BytesIO(b""))
        with self.assertRaises(PortError):
            fetch.extract(hostile, self.work / "out")

    def test_a_real_tarball_unpacks(self):
        bundle = self.work / "build.tar.gz"
        with tarfile.open(bundle, "w:gz") as archive:
            payload = b"binary"
            info = tarfile.TarInfo("horizon-client")
            info.size = len(payload)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(payload))
        destination = self.work / "out"
        fetch.extract(bundle, destination)
        self.assertEqual((destination / "horizon-client").read_bytes(), b"binary")

    def test_missing_programs_are_named(self):
        folder = self.work / "empty"
        folder.mkdir()
        self.assertEqual(sorted(fetch.missing_programs(folder)), ["horizon-client", "horizon-prepare", "research-lock.json"])


if __name__ == "__main__":
    unittest.main()
