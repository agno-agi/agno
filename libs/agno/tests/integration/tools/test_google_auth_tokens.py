import os
import tempfile

import pytest
from google.oauth2.credentials import Credentials

from agno.db.sqlite.sqlite import SqliteDb
from agno.tools.google.auth.tokens import (
    delete_token_from_db,
    load_token_from_db,
    save_token_to_db,
)
from agno.utils.encryption import generate_encryption_key

ENCRYPTION_KEY = generate_encryption_key()
WRONG_KEY = generate_encryption_key()
TOKEN_URI = "https://oauth2.googleapis.com/token"
SCOPES = ["https://mail.google.com/"]


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    sqlite_db = SqliteDb(db_file=path)
    yield sqlite_db
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def creds():
    return Credentials(
        token="access_token_value",
        refresh_token="refresh_token_value",
        token_uri=TOKEN_URI,
        client_id="client_id_value",
        client_secret="client_secret_value",
    )


# ============================================================================
# FULL FLOW: SAVE -> LOAD -> DELETE
# ============================================================================


def test_full_encrypted_token_lifecycle(db, creds):
    # 1. Save encrypted
    saved = save_token_to_db(db, creds, SCOPES, ENCRYPTION_KEY, encrypt_tokens=True)
    assert saved is True

    # 2. Verify encrypted in DB (no plaintext leak)
    raw = db.get_auth_token("google", None, "google")
    assert "encrypted" in raw["token_data"]
    assert "access_token_value" not in str(raw["token_data"])

    # 3. Load and verify real Credentials object
    row, loaded = load_token_from_db(db, ENCRYPTION_KEY)
    assert row is not None
    assert isinstance(loaded, Credentials)
    assert loaded.token == creds.token
    assert loaded.refresh_token == creds.refresh_token
    assert loaded.client_id == creds.client_id
    assert loaded.client_secret == creds.client_secret

    # 4. Delete
    deleted = delete_token_from_db(db)
    assert deleted is True

    # 5. Verify gone
    row, loaded = load_token_from_db(db, ENCRYPTION_KEY)
    assert row is None
    assert loaded is None


def test_full_plaintext_token_lifecycle(db, creds):
    # 1. Save plaintext
    saved = save_token_to_db(db, creds, SCOPES, encryption_key=None, encrypt_tokens=False)
    assert saved is True

    # 2. Verify plaintext in DB
    raw = db.get_auth_token("google", None, "google")
    assert raw["token_data"]["token"] == "access_token_value"
    assert "encrypted" not in raw["token_data"]

    # 3. Load and verify
    row, loaded = load_token_from_db(db, encryption_key=None)
    assert isinstance(loaded, Credentials)
    assert loaded.token == creds.token

    # 4. Delete
    assert delete_token_from_db(db) is True
    row, _ = load_token_from_db(db, None)
    assert row is None


# ============================================================================
# ENCRYPTION SECURITY
# ============================================================================


def test_wrong_key_cannot_decrypt(db, creds):
    save_token_to_db(db, creds, SCOPES, ENCRYPTION_KEY, encrypt_tokens=True)

    row, loaded = load_token_from_db(db, WRONG_KEY)
    assert row is None
    assert loaded is None


def test_no_key_refuses_to_save_when_required(db, creds):
    saved = save_token_to_db(db, creds, SCOPES, encryption_key=None, encrypt_tokens=True)
    assert saved is False

    raw = db.get_auth_token("google", None, "google")
    assert raw is None


# ============================================================================
# SCOPES
# ============================================================================


def test_granted_scopes_round_trip(db, creds):
    multi_scopes = ["https://mail.google.com/", "https://www.googleapis.com/auth/calendar"]

    save_token_to_db(db, creds, multi_scopes, ENCRYPTION_KEY, encrypt_tokens=True)

    row, loaded = load_token_from_db(db, ENCRYPTION_KEY)
    assert row["granted_scopes"] == multi_scopes
    assert loaded.scopes == multi_scopes


# ============================================================================
# MIGRATION: PLAINTEXT -> ENCRYPTED
# ============================================================================


def test_upgrade_plaintext_to_encrypted(db, creds):
    # 1. Save as plaintext (legacy)
    save_token_to_db(db, creds, SCOPES, encryption_key=None, encrypt_tokens=False)
    raw = db.get_auth_token("google", None, "google")
    assert "token" in raw["token_data"]

    # 2. Re-save with encryption
    save_token_to_db(db, creds, SCOPES, ENCRYPTION_KEY, encrypt_tokens=True)
    raw = db.get_auth_token("google", None, "google")
    assert list(raw["token_data"].keys()) == ["encrypted"]

    # 3. Verify still loadable
    _, loaded = load_token_from_db(db, ENCRYPTION_KEY)
    assert loaded.token == creds.token
