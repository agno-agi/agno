"""Unit tests for SuperGrok token storage: DB row shape, encryption, degrade paths.

The stored row maps field-for-field onto the Google auth token row
(agno_auth_tokens), with PR 1 using the empty-string single-user slot.
"""

import json
import os
import stat
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.xai import oauth
from agno.models.xai.oauth import XAI_OAUTH_SCOPE, XAI_TOKEN_URL, XAITokenManager
from agno.models.xai.responses import xAIResponses
from agno.utils.encryption import decrypt_dict, encrypt_dict, generate_encryption_key, is_encrypted


def _sync_manager(token_endpoint, **kwargs) -> XAITokenManager:
    return XAITokenManager(http_client=httpx.Client(transport=httpx.MockTransport(token_endpoint)), **kwargs)


# ---------------------------------------------------------------------------
# T9: storage round-trip on a real SqliteDb (sync + async twin)
# ---------------------------------------------------------------------------


def test_store_round_trip_sqlite(sqlite_db, encryption_key, token_endpoint, fake_clock):
    manager = _sync_manager(token_endpoint, db=sqlite_db, encryption_key=encryption_key, now_fn=fake_clock)

    manager.poll_for_token("device-code-1", interval=5, deadline=fake_clock() + 1800)

    row = sqlite_db.get_auth_token("xai", "", "supergrok")
    assert row["provider"] == "xai"
    assert row["user_id"] == ""
    assert row["service"] == "supergrok"
    assert row["granted_scopes"] == XAI_OAUTH_SCOPE.split()
    assert is_encrypted(row["token_data"])

    data = decrypt_dict(row["token_data"], key=encryption_key)
    assert data["access_token"] == "access-token-1"
    assert data["refresh_token"] == "refresh-token-1"
    assert data["id_token"] == "id-token-1"
    assert data["token_type"] == "Bearer"
    assert data["scope"] == XAI_OAUTH_SCOPE
    assert data["expires_at"] == int(fake_clock()) + 21600
    assert data["token_endpoint"] == XAI_TOKEN_URL

    assert manager.get_access_token() == "access-token-1"


async def test_store_round_trip_async_sqlite(async_sqlite_db, encryption_key, token_endpoint, fake_clock):
    async with httpx.AsyncClient(transport=httpx.MockTransport(token_endpoint)) as client:
        manager = XAITokenManager(
            db=async_sqlite_db,
            encryption_key=encryption_key,
            async_http_client=client,
            now_fn=fake_clock,
        )

        await manager.apoll_for_token("device-code-1", interval=5, deadline=fake_clock() + 1800)

        row = await async_sqlite_db.get_auth_token("xai", "", "supergrok")
        assert row["provider"] == "xai"
        assert row["user_id"] == ""
        assert row["service"] == "supergrok"
        assert is_encrypted(row["token_data"])

        data = decrypt_dict(row["token_data"], key=encryption_key)
        assert data["access_token"] == "access-token-1"
        assert data["expires_at"] == int(fake_clock()) + 21600

        assert await manager.aget_access_token() == "access-token-1"


# ---------------------------------------------------------------------------
# T10: degrade paths - missing key, decrypt failure, backend without support,
# file fallback permissions, memory-only mode
# ---------------------------------------------------------------------------


def test_save_without_key_refuses_and_warns(sqlite_db, token_endpoint, fake_clock, monkeypatch):
    monkeypatch.delenv("XAI_TOKEN_ENCRYPTION_KEY", raising=False)
    manager = _sync_manager(token_endpoint, db=sqlite_db, now_fn=fake_clock)

    with patch("agno.models.xai.oauth.log_warning") as mock_warning:
        manager.poll_for_token("device-code-1", interval=5, deadline=fake_clock() + 1800)

    assert any("XAI_TOKEN_ENCRYPTION_KEY" in str(call) for call in mock_warning.call_args_list)
    assert sqlite_db.get_auth_token("xai", "", "supergrok") is None


def test_encrypt_tokens_false_saves_plaintext(sqlite_db, token_endpoint, fake_clock, monkeypatch):
    monkeypatch.delenv("XAI_TOKEN_ENCRYPTION_KEY", raising=False)
    manager = _sync_manager(token_endpoint, db=sqlite_db, encrypt_tokens=False, now_fn=fake_clock)

    manager.poll_for_token("device-code-1", interval=5, deadline=fake_clock() + 1800)

    row = sqlite_db.get_auth_token("xai", "", "supergrok")
    assert not is_encrypted(row["token_data"])
    assert row["token_data"]["access_token"] == "access-token-1"


def test_decrypt_failure_warns_not_debug(sqlite_db, encryption_key, token_endpoint, fake_clock):
    other_key = generate_encryption_key()
    sqlite_db.upsert_auth_token(
        {
            "provider": "xai",
            "user_id": "",
            "service": "supergrok",
            "token_data": encrypt_dict(
                {"access_token": "access-token-1", "refresh_token": "refresh-token-1", "expires_at": 2_000_000},
                key=other_key,
            ),
            "granted_scopes": XAI_OAUTH_SCOPE.split(),
        }
    )
    manager = _sync_manager(token_endpoint, db=sqlite_db, encryption_key=encryption_key, now_fn=fake_clock)

    with (
        patch("agno.models.xai.oauth.log_warning") as mock_warning,
        patch("agno.models.xai.oauth.log_debug") as mock_debug,
    ):
        with pytest.raises(ModelAuthenticationError):
            manager.get_access_token()

    # Headless deployments cannot re-auth interactively: silent loss is the worse
    # failure, so a decrypt failure surfaces at warning level, never debug.
    assert any("decrypt" in str(call).lower() for call in mock_warning.call_args_list)
    assert not any("decrypt" in str(call).lower() for call in mock_debug.call_args_list)


def test_upsert_returning_none_warns_and_keeps_memory(token_endpoint, encryption_key, fake_clock):
    # Adapters swallow their own errors and signal a failed write by returning None;
    # losing a rotated refresh token silently would strand the session
    db = MagicMock()
    db.get_auth_token.return_value = None
    db.upsert_auth_token.return_value = None
    manager = _sync_manager(token_endpoint, db=db, encryption_key=encryption_key, now_fn=fake_clock)

    with patch("agno.models.xai.oauth.log_warning") as mock_warning:
        manager.poll_for_token("device-code-1", interval=5, deadline=fake_clock() + 1800)

    assert any("kept in memory" in str(call) for call in mock_warning.call_args_list)
    assert manager.get_access_token() == "access-token-1"


def test_no_decrypt_fallback_to_agno_key(sqlite_db, token_endpoint, fake_clock, monkeypatch):
    # The dedicated-key design: an encrypted row is never decrypted with
    # AGNO_ENCRYPTION_KEY, even when that key would work
    key = generate_encryption_key()
    sqlite_db.upsert_auth_token(
        {
            "provider": "xai",
            "user_id": "",
            "service": "supergrok",
            "token_data": encrypt_dict(
                {"access_token": "access-token-1", "refresh_token": "refresh-token-1", "expires_at": 2_000_000},
                key=key,
            ),
            "granted_scopes": XAI_OAUTH_SCOPE.split(),
        }
    )
    monkeypatch.delenv("XAI_TOKEN_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("AGNO_ENCRYPTION_KEY", key)
    manager = _sync_manager(token_endpoint, db=sqlite_db, now_fn=fake_clock)

    with patch("agno.models.xai.oauth.log_warning") as mock_warning:
        with pytest.raises(ModelAuthenticationError):
            manager.get_access_token()

    assert any("XAI_TOKEN_ENCRYPTION_KEY" in str(call) for call in mock_warning.call_args_list)


def test_sync_path_with_async_db_warns_and_uses_file(
    async_sqlite_db, tmp_path, encryption_key, token_endpoint, fake_clock
):
    # An async backend on the sync path must degrade loudly, never fire-and-forget a coroutine
    token_file = tmp_path / "xai_token.json"
    manager = _sync_manager(
        token_endpoint, db=async_sqlite_db, token_path=str(token_file), encryption_key=encryption_key, now_fn=fake_clock
    )

    with patch("agno.models.xai.oauth.log_warning") as mock_warning:
        manager.poll_for_token("device-code-1", interval=5, deadline=fake_clock() + 1800)

    assert any("async token methods" in str(call) for call in mock_warning.call_args_list)
    assert token_file.exists()
    assert manager.get_access_token() == "access-token-1"


def test_not_implemented_backend_falls_back_to_file(tmp_path, encryption_key, token_endpoint, fake_clock):
    db = MagicMock()
    db.get_auth_token.side_effect = NotImplementedError
    db.upsert_auth_token.side_effect = NotImplementedError
    db.delete_auth_token.side_effect = NotImplementedError
    token_file = tmp_path / "xai_token.json"
    manager = _sync_manager(
        token_endpoint, db=db, token_path=str(token_file), encryption_key=encryption_key, now_fn=fake_clock
    )

    with patch("agno.models.xai.oauth.log_warning") as mock_warning:
        manager.poll_for_token("device-code-1", interval=5, deadline=fake_clock() + 1800)

    mock_warning.assert_any_call("Database does not support auth token storage")
    assert token_file.exists()
    assert is_encrypted(json.loads(token_file.read_text()))


def test_file_fallback_written_0600(tmp_path, encryption_key, token_endpoint, fake_clock):
    token_file = tmp_path / "xai_token.json"
    manager = _sync_manager(
        token_endpoint, token_path=str(token_file), encryption_key=encryption_key, now_fn=fake_clock
    )

    manager.poll_for_token("device-code-1", interval=5, deadline=fake_clock() + 1800)

    assert stat.S_IMODE(os.stat(token_file).st_mode) == 0o600
    contents = json.loads(token_file.read_text())
    assert is_encrypted(contents)
    assert decrypt_dict(contents, key=encryption_key)["access_token"] == "access-token-1"

    # A fresh manager (new process) reads the file back
    oauth._reset_cache_for_tests()
    second = _sync_manager(token_endpoint, token_path=str(token_file), encryption_key=encryption_key, now_fn=fake_clock)
    assert second.get_access_token() == "access-token-1"


def test_memory_only_when_file_unwritable(tmp_path, encryption_key, token_endpoint, fake_clock):
    token_file = tmp_path / "missing-dir" / "xai_token.json"
    manager = _sync_manager(
        token_endpoint, token_path=str(token_file), encryption_key=encryption_key, now_fn=fake_clock
    )

    with patch("agno.models.xai.oauth.log_warning") as mock_warning:
        manager.poll_for_token("device-code-1", interval=5, deadline=fake_clock() + 1800)

    # The warning must carry the persistence-loss meaning, not just exist
    assert any("Token kept in memory only" in str(call) for call in mock_warning.call_args_list)
    assert not token_file.exists()
    # Still functional for the process lifetime
    assert manager.get_access_token() == "access-token-1"


# ---------------------------------------------------------------------------
# T11: isolation - OAuth mode never reads env keys; API-key mode never touches
# the token store
# ---------------------------------------------------------------------------


def test_oauth_mode_never_reads_env_keys():
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-should-not-leak", "XAI_API_KEY": "xai-env-key"}, clear=True):
        model = xAIResponses(token_provider=lambda: "tok")
        params = model._get_client_params()

    assert "api_key" not in params
    assert model.api_key is None


def test_api_key_mode_never_touches_token_store():
    manager = MagicMock()
    model = xAIResponses(api_key="explicit-key", token_manager=manager)

    params = model._get_client_params()
    assert params["api_key"] == "explicit-key"

    model.get_client()
    assert manager.method_calls == []


# ---------------------------------------------------------------------------
# Per-user isolation of the last-resort memory slot
#
# _memory_row is the third store, under the db row and the file. The cache is
# already keyed (provider, user_id, service) and the row key follows _store_key,
# so this slot is the only one with no key - and _load falls back to it whenever
# the store misses, which is what an absent per-user row looks like.
# ---------------------------------------------------------------------------


def test_the_memory_slot_does_not_serve_one_users_token_to_another(
    sqlite_db, encryption_key, token_endpoint, fake_clock
):
    manager = _sync_manager(token_endpoint, db=sqlite_db, encryption_key=encryption_key, now_fn=fake_clock)

    manager._save({"access_token": "user-a-token", "expires_at": fake_clock() + 21600}, user_id="u1")

    # u1's row really is in the store, so this is not a "no backend" degrade:
    # u2 simply has no row, which is the ordinary case for a second user.
    assert sqlite_db.get_auth_token("xai", "u1", "supergrok") is not None
    assert manager._load(user_id="u2") is None


async def test_the_memory_slot_does_not_serve_one_users_token_to_another_async(
    sqlite_db, encryption_key, token_endpoint, fake_clock
):
    manager = XAITokenManager(
        async_http_client=httpx.AsyncClient(transport=httpx.MockTransport(token_endpoint)),
        db=sqlite_db,
        encryption_key=encryption_key,
        now_fn=fake_clock,
    )

    await manager._asave({"access_token": "user-a-token", "expires_at": fake_clock() + 21600}, user_id="u1")

    assert sqlite_db.get_auth_token("xai", "u1", "supergrok") is not None
    assert await manager._aload(user_id="u2") is None


def test_signing_one_user_out_leaves_another_users_memory_token(token_endpoint, fake_clock, tmp_path):
    """sign_out pops one user's entry; it must never clear the whole slot.

    No db on purpose: the file store refuses an identified user, so memory is
    the only place these two tokens live and the assertion is about the slot.
    """
    manager = _sync_manager(
        token_endpoint, token_path=str(tmp_path / "token.json"), encrypt_tokens=False, now_fn=fake_clock
    )
    manager._save({"access_token": "user-a-token", "expires_at": fake_clock() + 21600}, user_id="u1")
    manager._save({"access_token": "user-b-token", "expires_at": fake_clock() + 21600}, user_id="u2")

    manager.sign_out(user_id="u1")

    assert manager._load(user_id="u1") is None
    assert (manager._load(user_id="u2") or {})["access_token"] == "user-b-token"


def test_signing_a_user_out_leaves_the_deployment_token_file_alone(token_endpoint, fake_clock, tmp_path):
    """The file store holds ONE session - the deployment's. A user cannot delete it.

    The read and write paths already refuse an identified user; the delete path
    is the one that did not, so an identified sign_out unlinked the shared file.
    """
    path = tmp_path / "token.json"
    manager = _sync_manager(token_endpoint, token_path=str(path), encrypt_tokens=False, now_fn=fake_clock)
    manager._save({"access_token": "deployment-token", "expires_at": fake_clock() + 21600}, user_id="")

    manager.sign_out(user_id="u1")

    assert path.exists()
    assert (manager._load() or {})["access_token"] == "deployment-token"


@pytest.mark.asyncio
async def test_signing_a_user_out_asynchronously_leaves_the_deployment_token_file_alone(
    token_endpoint, fake_clock, tmp_path
):
    """The async twin carries the same guard - it is a byte-duplicate of the sync one."""
    path = tmp_path / "token.json"
    manager = _sync_manager(token_endpoint, token_path=str(path), encrypt_tokens=False, now_fn=fake_clock)
    manager._save({"access_token": "deployment-token", "expires_at": fake_clock() + 21600}, user_id="")

    await manager.asign_out(user_id="u1")

    assert path.exists()
    assert (manager._load() or {})["access_token"] == "deployment-token"
