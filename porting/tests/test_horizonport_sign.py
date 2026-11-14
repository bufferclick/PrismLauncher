import base64
import hashlib
import unittest

from porting.horizonport import sign
from porting.horizonport.util import PortError


def ed25519_public_key(seed: bytes) -> bytes:
    """RFC 8032 key generation, for the tests that need to sign their own sums."""
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return sign._encode(sign._scalar_mul(scalar, sign._BASE))


def ed25519_sign(seed: bytes, message: bytes) -> bytes:
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    public = sign._encode(sign._scalar_mul(scalar, sign._BASE))
    nonce = int.from_bytes(hashlib.sha512(digest[32:] + message).digest(), "little") % sign._L
    r = sign._encode(sign._scalar_mul(nonce, sign._BASE))
    challenge = int.from_bytes(hashlib.sha512(r + public + message).digest(), "little") % sign._L
    s = (nonce + challenge * scalar) % sign._L
    return r + s.to_bytes(32, "little")


class Ed25519Tests(unittest.TestCase):
    # RFC 8032, section 7.1: the two published test vectors with known answers.
    def test_rfc8032_vector_1(self):
        key = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        signature = bytes.fromhex(
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bac"
            "c61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
        )
        self.assertTrue(sign.ed25519_verify(key, b"", signature))

    def test_rfc8032_vector_2(self):
        key = bytes.fromhex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")
        signature = bytes.fromhex(
            "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e"
            "458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
        )
        self.assertTrue(sign.ed25519_verify(key, bytes([0x72]), signature))

    def test_another_message_is_refused(self):
        key = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        signature = bytes.fromhex(
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bac"
            "c61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
        )
        self.assertFalse(sign.ed25519_verify(key, b"x", signature))

    def test_round_trip_with_a_generated_key(self):
        seed = bytes(range(32))
        key = ed25519_public_key(seed)
        message = b"horizon release nightly\nabc  file.zip\n"
        signature = ed25519_sign(seed, message)
        self.assertTrue(sign.ed25519_verify(key, message, signature))
        self.assertFalse(sign.ed25519_verify(key, message + b" ", signature))


class ChecksumTests(unittest.TestCase):
    def setUp(self):
        self.seed = bytes(range(32))
        self.key = ed25519_public_key(self.seed)
        self.sums = b"a" * 64 + b"  horizon-linux-x86_64.tar.gz\n" + b"b" * 64 + b"  SHA256SUMS\n"

    def signature(self, tag="nightly"):
        return base64.b64encode(ed25519_sign(self.seed, sign.message(tag, self.sums))).decode()

    def test_a_signed_list_verifies_and_lists_files(self):
        files = sign.verify_sums("nightly", self.sums, self.signature(), [self.key])
        self.assertEqual([name for name, _ in files], ["horizon-linux-x86_64.tar.gz", "SHA256SUMS"])

    def test_the_wrong_tag_is_refused(self):
        with self.assertRaises(PortError):
            sign.verify_sums("nightly-2026-11-05", self.sums, self.signature(), [self.key])

    def test_an_edited_checksum_list_is_refused(self):
        edited = self.sums.replace(b"a" * 64, b"c" * 64)
        with self.assertRaises(PortError):
            sign.verify_sums("nightly", edited, self.signature(), [self.key])

    def test_another_key_is_refused(self):
        other = ed25519_public_key(bytes(range(1, 33)))
        with self.assertRaises(PortError):
            sign.verify_sums("nightly", self.sums, self.signature(), [other])

    def test_no_key_means_no_install(self):
        with self.assertRaises(PortError):
            sign.verify_sums("nightly", self.sums, self.signature(), [])

    def test_a_malformed_sums_line_is_refused(self):
        with self.assertRaises(PortError):
            sign.parse_sums("not-a-checksum  file.zip\n")

    def test_lookup_names_the_missing_file(self):
        files = sign.parse_sums(self.sums.decode())
        self.assertEqual(sign.lookup(files, "SHA256SUMS"), "b" * 64)
        with self.assertRaises(PortError):
            sign.lookup(files, "horizon-windows-x64.zip")

    def test_the_built_in_key_is_a_valid_ed25519_key(self):
        keys = sign.default_keys()
        self.assertTrue(keys)
        self.assertEqual(len(keys[0]), 32)


if __name__ == "__main__":
    unittest.main()
