import pytest

# Valid Fernet key for testing (generated via Fernet.generate_key())
TEST_KEY = "dGVzdC1rZXktZm9yLXVuaXQtdGVzdHMtMzJieXRlcw=="
TEST_KEY_2 = "YW5vdGhlci10ZXN0LWtleS1mb3ItdGVzdGluZy0zMg=="


# ============================================================================
# generate_encryption_key TESTS
# ============================================================================


def test_generate_encryption_key_returns_string():
    from agno.utils.encryption import generate_encryption_key

    result = generate_encryption_key()
    assert isinstance(result, str)


def test_generate_encryption_key_returns_44_chars():
    from agno.utils.encryption import generate_encryption_key

    result = generate_encryption_key()
    assert len(result) == 44


def test_generate_encryption_key_is_valid_fernet_key():
    from cryptography.fernet import Fernet

    from agno.utils.encryption import generate_encryption_key

    key = generate_encryption_key()
    # Should not raise
    Fernet(key.encode())


def test_generate_encryption_key_unique():
    from agno.utils.encryption import generate_encryption_key

    key1 = generate_encryption_key()
    key2 = generate_encryption_key()
    assert key1 != key2


# ============================================================================
# _validate_fernet_key TESTS
# ============================================================================


def test_validate_fernet_key_accepts_valid_key():
    from agno.utils.encryption import _validate_fernet_key, generate_encryption_key

    key = generate_encryption_key()
    result = _validate_fernet_key(key)
    assert isinstance(result, bytes)
    assert len(result) == 44


def test_validate_fernet_key_rejects_short_string():
    from agno.utils.encryption import _validate_fernet_key

    with pytest.raises(ValueError, match="Invalid encryption key"):
        _validate_fernet_key("too-short")


def test_validate_fernet_key_rejects_password():
    from agno.utils.encryption import _validate_fernet_key

    with pytest.raises(ValueError, match="Invalid encryption key"):
        _validate_fernet_key("my-secret-password-123")


def test_validate_fernet_key_rejects_wrong_length():
    from agno.utils.encryption import _validate_fernet_key

    with pytest.raises(ValueError, match="Invalid encryption key"):
        _validate_fernet_key("x" * 43)  # 43 chars instead of 44


# ============================================================================
# get_encryption_key TESTS
# ============================================================================


def test_get_encryption_key_from_env(monkeypatch):
    from agno.utils.encryption import get_encryption_key

    monkeypatch.setenv("AGNO_ENCRYPTION_KEY", TEST_KEY)
    assert get_encryption_key() == TEST_KEY


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
    from agno.utils.encryption import encrypt_dict, generate_encryption_key

    key = generate_encryption_key()
    data = {"key": "value"}
    result = encrypt_dict(data, key=key)

    assert "encrypted" in result
    assert len(result) == 1
    assert "key" not in result


def test_encrypt_dict_ciphertext_not_plaintext():
    from agno.utils.encryption import encrypt_dict, generate_encryption_key

    key = generate_encryption_key()
    data = {"sensitive": "password123"}
    result = encrypt_dict(data, key=key)

    assert "password123" not in result["encrypted"]
    assert "sensitive" not in result["encrypted"]


def test_encrypt_dict_uses_env_key(monkeypatch):
    from agno.utils.encryption import encrypt_dict, generate_encryption_key

    key = generate_encryption_key()
    monkeypatch.setenv("AGNO_ENCRYPTION_KEY", key)
    data = {"key": "value"}
    result = encrypt_dict(data)

    assert "encrypted" in result


def test_encrypt_dict_raises_without_key(monkeypatch):
    from agno.utils.encryption import encrypt_dict

    monkeypatch.delenv("AGNO_ENCRYPTION_KEY", raising=False)

    with pytest.raises(ValueError, match="No encryption key"):
        encrypt_dict({"key": "value"})


def test_encrypt_dict_raises_with_invalid_key():
    from agno.utils.encryption import encrypt_dict

    with pytest.raises(ValueError, match="Invalid encryption key"):
        encrypt_dict({"key": "value"}, key="weak-password")


# ============================================================================
# decrypt_dict TESTS
# ============================================================================


def test_decrypt_dict_round_trip():
    from agno.utils.encryption import decrypt_dict, encrypt_dict, generate_encryption_key

    key = generate_encryption_key()
    original = {"token": "access123", "nested": {"key": "value"}}
    encrypted = encrypt_dict(original, key=key)
    decrypted = decrypt_dict(encrypted, key=key)

    assert decrypted == original


def test_decrypt_dict_passthrough_unencrypted():
    from agno.utils.encryption import decrypt_dict, generate_encryption_key

    key = generate_encryption_key()
    data = {"plain": "text", "not": "encrypted"}
    result = decrypt_dict(data, key=key)

    assert result == data


def test_decrypt_dict_wrong_key_raises():
    from agno.utils.encryption import decrypt_dict, encrypt_dict, generate_encryption_key

    key1 = generate_encryption_key()
    key2 = generate_encryption_key()
    encrypted = encrypt_dict({"key": "value"}, key=key1)

    with pytest.raises(ValueError, match="wrong key"):
        decrypt_dict(encrypted, key=key2)


def test_decrypt_dict_corrupted_data_raises():
    from agno.utils.encryption import decrypt_dict, generate_encryption_key

    key = generate_encryption_key()
    corrupted = {"encrypted": "not-valid-base64!!!"}

    with pytest.raises((ValueError, Exception)):
        decrypt_dict(corrupted, key=key)


def test_decrypt_dict_uses_env_key(monkeypatch):
    from agno.utils.encryption import decrypt_dict, encrypt_dict, generate_encryption_key

    key = generate_encryption_key()
    monkeypatch.setenv("AGNO_ENCRYPTION_KEY", key)
    encrypted = encrypt_dict({"key": "value"}, key=key)
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
    from agno.utils.encryption import decrypt_dict, encrypt_dict, generate_encryption_key

    key = generate_encryption_key()
    original = {}
    encrypted = encrypt_dict(original, key=key)
    decrypted = decrypt_dict(encrypted, key=key)

    assert decrypted == original


def test_round_trip_complex_nested():
    from agno.utils.encryption import decrypt_dict, encrypt_dict, generate_encryption_key

    key = generate_encryption_key()
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
    encrypted = encrypt_dict(original, key=key)
    decrypted = decrypt_dict(encrypted, key=key)

    assert decrypted == original


def test_round_trip_unicode():
    from agno.utils.encryption import decrypt_dict, encrypt_dict, generate_encryption_key

    key = generate_encryption_key()
    original = {"message": "Hello, 世界! \U0001f44b"}
    encrypted = encrypt_dict(original, key=key)
    decrypted = decrypt_dict(encrypted, key=key)

    assert decrypted == original


def test_round_trip_large_data():
    from agno.utils.encryption import decrypt_dict, encrypt_dict, generate_encryption_key

    key = generate_encryption_key()
    original = {"data": "x" * 10000}
    encrypted = encrypt_dict(original, key=key)
    decrypted = decrypt_dict(encrypted, key=key)

    assert decrypted == original
