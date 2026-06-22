from unittest.mock import patch

import pytest

# ============================================================================
# _derive_fernet_key TESTS
# ============================================================================


def test_derive_key_returns_bytes():
    from agno.utils.encryption import _derive_fernet_key

    result = _derive_fernet_key("test-secret")
    assert isinstance(result, bytes)


def test_derive_key_returns_44_char_base64():
    from agno.utils.encryption import _derive_fernet_key

    result = _derive_fernet_key("test-secret")
    assert len(result) == 44


def test_derive_key_deterministic():
    from agno.utils.encryption import _derive_fernet_key

    key1 = _derive_fernet_key("same-secret")
    key2 = _derive_fernet_key("same-secret")
    assert key1 == key2


def test_derive_key_different_secrets():
    from agno.utils.encryption import _derive_fernet_key

    key1 = _derive_fernet_key("secret-one")
    key2 = _derive_fernet_key("secret-two")
    assert key1 != key2


# ============================================================================
# get_encryption_key TESTS
# ============================================================================


def test_get_encryption_key_from_env(monkeypatch):
    from agno.utils.encryption import get_encryption_key

    monkeypatch.setenv("AGNO_ENCRYPTION_KEY", "my-secret")
    assert get_encryption_key() == "my-secret"


def test_get_encryption_key_returns_none(monkeypatch):
    from agno.utils.encryption import get_encryption_key

    monkeypatch.delenv("AGNO_ENCRYPTION_KEY", raising=False)
    assert get_encryption_key() is None


# ============================================================================
# is_encrypted TESTS
# ============================================================================


def test_is_encrypted_true():
    from agno.utils.encryption import is_encrypted

    data = {"encrypted": "some-base64-data"}
    assert is_encrypted(data) is True


def test_is_encrypted_false_for_plain_dict():
    from agno.utils.encryption import is_encrypted

    data = {"token": "value", "other": "field"}
    assert is_encrypted(data) is False


def test_is_encrypted_false_with_extra_keys():
    from agno.utils.encryption import is_encrypted

    data = {"encrypted": "data", "extra": "key"}
    assert is_encrypted(data) is False


def test_is_encrypted_false_for_empty_dict():
    from agno.utils.encryption import is_encrypted

    assert is_encrypted({}) is False


def test_is_encrypted_false_for_non_dict():
    from agno.utils.encryption import is_encrypted

    assert is_encrypted("string") is False
    assert is_encrypted(["list"]) is False
    assert is_encrypted(None) is False


# ============================================================================
# encrypt_dict TESTS
# ============================================================================


def test_encrypt_dict_returns_encrypted_format():
    from agno.utils.encryption import encrypt_dict

    data = {"key": "value"}
    result = encrypt_dict(data, key="test-secret")

    assert "encrypted" in result
    assert len(result) == 1
    assert "key" not in result


def test_encrypt_dict_ciphertext_not_plaintext():
    from agno.utils.encryption import encrypt_dict

    data = {"sensitive": "password123"}
    result = encrypt_dict(data, key="test-secret")

    assert "password123" not in result["encrypted"]
    assert "sensitive" not in result["encrypted"]


def test_encrypt_dict_uses_env_key(monkeypatch):
    from agno.utils.encryption import encrypt_dict

    monkeypatch.setenv("AGNO_ENCRYPTION_KEY", "env-secret")
    data = {"key": "value"}
    result = encrypt_dict(data)

    assert "encrypted" in result


def test_encrypt_dict_raises_without_key(monkeypatch):
    from agno.utils.encryption import encrypt_dict

    monkeypatch.delenv("AGNO_ENCRYPTION_KEY", raising=False)

    with pytest.raises(ValueError, match="No encryption key"):
        encrypt_dict({"key": "value"})


def test_encrypt_dict_raises_without_cryptography():
    from agno.utils.encryption import encrypt_dict

    with patch.dict("sys.modules", {"cryptography": None, "cryptography.fernet": None}):
        with pytest.raises(ImportError, match="cryptography"):
            encrypt_dict({"key": "value"}, key="secret")


# ============================================================================
# decrypt_dict TESTS
# ============================================================================


def test_decrypt_dict_round_trip():
    from agno.utils.encryption import decrypt_dict, encrypt_dict

    original = {"token": "access123", "nested": {"key": "value"}}
    encrypted = encrypt_dict(original, key="test-secret")
    decrypted = decrypt_dict(encrypted, key="test-secret")

    assert decrypted == original


def test_decrypt_dict_passthrough_unencrypted():
    from agno.utils.encryption import decrypt_dict

    data = {"plain": "text", "not": "encrypted"}
    result = decrypt_dict(data, key="any-key")

    assert result == data


def test_decrypt_dict_wrong_key_raises():
    from agno.utils.encryption import decrypt_dict, encrypt_dict

    encrypted = encrypt_dict({"key": "value"}, key="correct-key")

    with pytest.raises(ValueError, match="wrong key"):
        decrypt_dict(encrypted, key="wrong-key")


def test_decrypt_dict_corrupted_data_raises():
    from agno.utils.encryption import decrypt_dict

    corrupted = {"encrypted": "not-valid-base64!!!"}

    with pytest.raises((ValueError, Exception)):
        decrypt_dict(corrupted, key="test-secret")


def test_decrypt_dict_uses_env_key(monkeypatch):
    from agno.utils.encryption import decrypt_dict, encrypt_dict

    monkeypatch.setenv("AGNO_ENCRYPTION_KEY", "env-secret")
    encrypted = encrypt_dict({"key": "value"}, key="env-secret")
    decrypted = decrypt_dict(encrypted)

    assert decrypted == {"key": "value"}


def test_decrypt_dict_raises_without_key(monkeypatch):
    from agno.utils.encryption import decrypt_dict

    monkeypatch.delenv("AGNO_ENCRYPTION_KEY", raising=False)
    encrypted = {"encrypted": "some-ciphertext"}

    with pytest.raises(ValueError, match="no decryption key"):
        decrypt_dict(encrypted)


# ============================================================================
# ROUND TRIP TESTS
# ============================================================================


def test_round_trip_empty_dict():
    from agno.utils.encryption import decrypt_dict, encrypt_dict

    original = {}
    encrypted = encrypt_dict(original, key="secret")
    decrypted = decrypt_dict(encrypted, key="secret")

    assert decrypted == original


def test_round_trip_complex_nested():
    from agno.utils.encryption import decrypt_dict, encrypt_dict

    original = {
        "token": "access_token",
        "refresh_token": "refresh_token",
        "expiry": "2026-01-01T00:00:00Z",
        "scopes": ["gmail", "calendar"],
        "metadata": {
            "client_id": "id",
            "client_secret": "secret",
        },
    }
    encrypted = encrypt_dict(original, key="secret")
    decrypted = decrypt_dict(encrypted, key="secret")

    assert decrypted == original


def test_round_trip_unicode():
    from agno.utils.encryption import decrypt_dict, encrypt_dict

    original = {"message": "Hello, 世界! \U0001f44b"}
    encrypted = encrypt_dict(original, key="secret")
    decrypted = decrypt_dict(encrypted, key="secret")

    assert decrypted == original


def test_round_trip_large_data():
    from agno.utils.encryption import decrypt_dict, encrypt_dict

    original = {"data": "x" * 10000}
    encrypted = encrypt_dict(original, key="secret")
    decrypted = decrypt_dict(encrypted, key="secret")

    assert decrypted == original
