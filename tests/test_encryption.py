"""Tests for E2E encryption — core/encryption.py utilities.

Tests the pure cryptographic functions (no Supabase dependency).
"""

import pytest
import base64

from core.encryption import (
    _b64decode,
    _b64encode,
    build_share_url_with_key,
    decrypt_data,
    decrypt_with_password,
    derive_key_from_password,
    encrypt_data,
    encrypt_with_password,
    extract_key_from_url,
    generate_encryption_key,
    generate_iv,
    generate_salt,
    EncryptionResult,
    KeyBundle,
)


# ---------------------------------------------------------------------------
# Base64 helpers
# ---------------------------------------------------------------------------


class TestBase64Helpers:
    def test_roundtrip(self):
        for data in [b"hello", b"\x00\x01\x02\xff", b"a" * 100]:
            assert _b64decode(_b64encode(data)) == data

    def test_no_padding_in_output(self):
        """URL-safe base64 without padding — safe for URL fragments."""
        encoded = _b64encode(b"test data")
        assert "=" not in encoded
        assert "+" not in encoded
        assert "/" not in encoded or _b64decode(encoded) == b"test data"


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------


class TestKeyGeneration:
    def test_generate_key_bundle(self):
        bundle = generate_encryption_key()
        assert isinstance(bundle, KeyBundle)
        assert len(_b64decode(bundle.key)) == 32  # 256 bits
        assert len(_b64decode(bundle.iv)) == 12   # 96 bits
        assert len(_b64decode(bundle.salt)) == 16  # 128 bits

    def test_keys_are_unique(self):
        b1 = generate_encryption_key()
        b2 = generate_encryption_key()
        assert b1.key != b2.key
        assert b1.iv != b2.iv
        assert b1.salt != b2.salt

    def test_generate_iv(self):
        iv = generate_iv()
        assert len(_b64decode(iv)) == 12

    def test_generate_salt(self):
        salt = generate_salt()
        assert len(_b64decode(salt)) == 16


# ---------------------------------------------------------------------------
# AES-256-GCM encrypt/decrypt
# ---------------------------------------------------------------------------


class TestAESGCM:
    def test_encrypt_decrypt_roundtrip(self):
        key = b"\x00" * 32
        iv = b"\x01" * 12
        plaintext = b"Hello, DropItX E2E!"

        ciphertext = encrypt_data(plaintext, key, iv)
        assert ciphertext != plaintext
        assert len(ciphertext) > len(plaintext)  # GCM tag appended

        decrypted = decrypt_data(ciphertext, key, iv)
        assert decrypted == plaintext

    def test_encrypt_different_ivs(self):
        """Same plaintext with different IVs produces different ciphertexts."""
        key = b"\x00" * 32
        iv1 = b"\x01" * 12
        iv2 = b"\x02" * 12
        plaintext = b"same content"

        ct1 = encrypt_data(plaintext, key, iv1)
        ct2 = encrypt_data(plaintext, key, iv2)
        assert ct1 != ct2

    def test_decrypt_wrong_key_fails(self):
        key = b"\x00" * 32
        iv = b"\x01" * 12
        ciphertext = encrypt_data(b"secret", key, iv)

        wrong_key = b"\xff" * 32
        with pytest.raises(Exception):  # InvalidTag
            decrypt_data(ciphertext, wrong_key, iv)

    def test_decrypt_wrong_iv_fails(self):
        key = b"\x00" * 32
        iv = b"\x01" * 12
        ciphertext = encrypt_data(b"secret", key, iv)

        wrong_iv = b"\x02" * 12
        with pytest.raises(Exception):  # InvalidTag
            decrypt_data(ciphertext, key, wrong_iv)

    def test_tampered_ciphertext_fails(self):
        key = b"\x00" * 32
        iv = b"\x01" * 12
        ciphertext = bytearray(encrypt_data(b"secret", key, iv))
        ciphertext[0] ^= 0xFF  # tamper

        with pytest.raises(Exception):  # InvalidTag
            decrypt_data(bytes(ciphertext), key, iv)

    def test_empty_plaintext(self):
        key = b"\x00" * 32
        iv = b"\x01" * 12
        ct = encrypt_data(b"", key, iv)
        assert decrypt_data(ct, key, iv) == b""

    def test_large_data(self):
        key = b"\x00" * 32
        iv = b"\x01" * 12
        plaintext = b"x" * (1024 * 1024)  # 1 MB
        ct = encrypt_data(plaintext, key, iv)
        assert decrypt_data(ct, key, iv) == plaintext


# ---------------------------------------------------------------------------
# PBKDF2 key derivation
# ---------------------------------------------------------------------------


class TestPBKDF2:
    def test_derive_key_length(self):
        key = derive_key_from_password("password123", generate_salt())
        assert len(key) == 32

    def test_same_password_same_salt_same_key(self):
        salt = generate_salt()
        k1 = derive_key_from_password("mypassword", salt)
        k2 = derive_key_from_password("mypassword", salt)
        assert k1 == k2

    def test_same_password_different_salt_different_key(self):
        s1 = generate_salt()
        s2 = generate_salt()
        k1 = derive_key_from_password("mypassword", s1)
        k2 = derive_key_from_password("mypassword", s2)
        assert k1 != k2

    def test_different_password_same_salt_different_key(self):
        salt = generate_salt()
        k1 = derive_key_from_password("password1", salt)
        k2 = derive_key_from_password("password2", salt)
        assert k1 != k2


# ---------------------------------------------------------------------------
# High-level encrypt/decrypt with password
# ---------------------------------------------------------------------------


class TestPasswordEncryption:
    def test_roundtrip(self):
        plaintext = b"DropItX E2E encryption test content"
        password = "super-secret-password"

        result = encrypt_with_password(plaintext, password)
        assert isinstance(result, EncryptionResult)
        assert result.ciphertext != plaintext
        assert result.iv is not None
        assert result.salt is not None

        decrypted = decrypt_with_password(
            result.ciphertext, password, result.iv, result.salt
        )
        assert decrypted == plaintext

    def test_wrong_password_fails(self):
        plaintext = b"secret data"
        result = encrypt_with_password(plaintext, "correct-password")

        with pytest.raises(Exception):
            decrypt_with_password(
                result.ciphertext, "wrong-password", result.iv, result.salt
            )

    def test_different_encryptions_different_results(self):
        """Two encryptions of same plaintext with same password differ (random IV/salt)."""
        plaintext = b"same content"
        password = "same-pass"

        r1 = encrypt_with_password(plaintext, password)
        r2 = encrypt_with_password(plaintext, password)

        assert r1.ciphertext != r2.ciphertext
        assert r1.iv != r2.iv
        assert r1.salt != r2.salt

    def test_binary_content(self):
        """Encrypt arbitrary binary data, not just UTF-8."""
        plaintext = bytes(range(256)) * 100  # all byte values
        password = "binary-test"

        result = encrypt_with_password(plaintext, password)
        decrypted = decrypt_with_password(
            result.ciphertext, password, result.iv, result.salt
        )
        assert decrypted == plaintext

    def test_unicode_password(self):
        plaintext = b"hello"
        password = "パスワード🔐"

        result = encrypt_with_password(plaintext, password)
        decrypted = decrypt_with_password(
            result.ciphertext, password, result.iv, result.salt
        )
        assert decrypted == plaintext


# ---------------------------------------------------------------------------
# URL fragment helpers
# ---------------------------------------------------------------------------


class TestURLFragments:
    def test_build_url_with_key(self):
        url = build_share_url_with_key("https://dropitx.com", "abc123", "mySecretKey")
        assert url == "https://dropitx.com/s/abc123#mySecretKey"

    def test_extract_key_from_url(self):
        url = "https://dropitx.com/s/abc123#encryptionKeyHere"
        assert extract_key_from_url(url) == "encryptionKeyHere"

    def test_extract_key_no_fragment(self):
        assert extract_key_from_url("https://dropitx.com/s/abc123") is None

    def test_extract_key_empty_fragment(self):
        assert extract_key_from_url("https://dropitx.com/s/abc123#") == ""

    def test_fragment_not_sent_to_server(self):
        """Verify the key is in the fragment (after #), which browsers don't send."""
        key = "supersecretkey123"
        url = build_share_url_with_key("https://dropitx.com", "slug", key)
        # Fragment is after #
        fragment = url.split("#")[1]
        assert fragment == key
        # URL path doesn't contain the key
        path_part = url.split("#")[0]
        assert key not in path_part


# ---------------------------------------------------------------------------
# Compatibility with Web Crypto API format
# ---------------------------------------------------------------------------


class TestWebCryptoCompatibility:
    """Verify our key/IV/salt format is compatible with Web Crypto API.

    Web Crypto expects raw bytes or JWK format.
    Our base64url encoding matches the standard for key import.
    """

    def test_key_is_valid_base64url(self):
        bundle = generate_encryption_key()
        # Should decode without error
        key_bytes = _b64decode(bundle.key)
        assert len(key_bytes) == 32

    def test_iv_is_valid_base64url(self):
        bundle = generate_encryption_key()
        iv_bytes = _b64decode(bundle.iv)
        assert len(iv_bytes) == 12

    def test_salt_is_valid_base64url(self):
        bundle = generate_encryption_key()
        salt_bytes = _b64decode(bundle.salt)
        assert len(salt_bytes) == 16

    def test_base64url_no_special_chars(self):
        """Base64url output should be safe for URL fragments."""
        for _ in range(100):
            bundle = generate_encryption_key()
            for val in [bundle.key, bundle.iv, bundle.salt]:
                # No standard base64 chars that are URL-unsafe
                assert "+" not in val
                assert "/" not in val
                assert "=" not in val
