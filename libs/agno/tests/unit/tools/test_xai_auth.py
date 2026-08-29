"""Contract tests for the XAIAuth chat sign-in toolkit.

Fixture values mirror PR 1's OAuth suite (device grant expires_in 1800, poll
interval 5, token lifetime 21600) so both suites encode one contract. The
toolkit consumes the token manager unmodified: the final token row stays at
("xai", "", "supergrok") and only the pending-login row is toolkit-owned.
"""

import json
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock
from urllib.parse import parse_qsl

import httpx
import pytest

from agno.models.xai.oauth import XAI_DEVICE_CODE_URL, XAI_OAUTH_SCOPE, XAITokenManager
from agno.run import RunContext
from agno.tools.xai_auth import XAIAuth
from agno.utils.encryption import decrypt_dict, encrypt_dict, generate_encryption_key, is_encrypted

STORE_KEY = ("xai", "", "supergrok")  # the deployment slot: script users and shared deployments
USER_KEY = ("xai", "u1", "supergrok")  # a signed-in user spends their own subscription
PENDING_SERVICE = "supergrok-pending"

SIGN_IN_MESSAGE = (
    "Open this link, check the code matches, and approve the sign-in. Code: ABCD-1234. Then tell me when you're done."
)
APPROVAL_URL = "https://auth.x.ai/activate?user_code=ABCD-1234"
ALREADY_SIGNED_IN = (
    "Already signed in with SuperGrok (token valid). To sign in with a different account, "
    "say 'sign out and sign in again' — I'll restart the login."
)
SIGNED_IN = "Signed in with SuperGrok. The xAI model will now use this subscription."
SIGNED_IN_PER_USER = "Signed in with SuperGrok. Requests you make will now use this subscription."
NOT_APPROVED = "Not approved yet. Open the link, approve the sign-in, then tell me again when you're done."
NO_SIGN_IN = "No sign-in is in progress. Call sign_in_with_supergrok first."
NOT_SAVED = (
    "Signed in, but the token was NOT saved: XAI_TOKEN_ENCRYPTION_KEY is not set. "
    "Set it (see the cookbook) and sign in again, or pass encrypt_tokens=False for local dev."
)
FILE_DEGRADE_NOTE = " (Note: token stored to a local file — this database does not support token storage.)"
MEMORY_DEGRADE_NOTE = (
    " (Note: the token is kept in memory for this process only - a per-user sign-in needs a database "
    "that supports token storage.)"
)


@pytest.fixture(autouse=True)
def _reset_oauth_cache():
    """Reset the module-level token cache so no test depends on execution order."""
    from agno.models.xai import oauth

    oauth._reset_cache_for_tests()
    yield
    oauth._reset_cache_for_tests()


@pytest.fixture
def encryption_key() -> str:
    return generate_encryption_key()


@pytest.fixture
def device_response() -> Dict[str, Any]:
    return {
        "device_code": "device-code-1",
        "user_code": "ABCD-1234",
        "verification_uri": "https://auth.x.ai/activate",
        "verification_uri_complete": APPROVAL_URL,
        "expires_in": 1800,
        "interval": 5,
    }


@pytest.fixture
def token_response() -> Dict[str, Any]:
    return {
        "access_token": "access-token-1",
        "refresh_token": "refresh-token-1",
        "id_token": "id-token-1",
        "token_type": "Bearer",
        "scope": XAI_OAUTH_SCOPE,
        "expires_in": 21600,
    }


class AuthEndpoint:
    """MockTransport handler for auth.x.ai: device grants plus scripted poll outcomes."""

    def __init__(self, device_json: Dict[str, Any], token_json: Dict[str, Any]):
        self.device_json = device_json
        self.token_json = token_json
        self.queued: List[Tuple[int, Dict[str, Any]]] = []
        self.device_requests: List[Dict[str, str]] = []
        self.poll_requests: List[Dict[str, str]] = []

    def queue_poll(self, status_code: int, body: Dict[str, Any]) -> None:
        """Script the next poll response; unscripted polls return the success token."""
        self.queued.append((status_code, body))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        fields = dict(parse_qsl(request.content.decode()))
        if str(request.url) == XAI_DEVICE_CODE_URL:
            self.device_requests.append(fields)
            return httpx.Response(200, json=self.device_json)
        self.poll_requests.append(fields)
        if self.queued:
            status_code, body = self.queued.pop(0)
            return httpx.Response(status_code, json=body)
        return httpx.Response(200, json=self.token_json)


@pytest.fixture
def endpoint(device_response, token_response) -> AuthEndpoint:
    return AuthEndpoint(device_response, token_response)


@pytest.fixture
def sqlite_db(tmp_path):
    from agno.db.sqlite import SqliteDb

    return SqliteDb(db_file=str(tmp_path / "auth.db"))


def _toolkit(endpoint: AuthEndpoint, **manager_kwargs: Any) -> XAIAuth:
    """A toolkit whose manager talks to the mock endpoint."""
    manager = XAITokenManager(http_client=httpx.Client(transport=httpx.MockTransport(endpoint)), **manager_kwargs)
    return XAIAuth(token_manager=manager)


def _ctx(user_id: Optional[str] = None) -> RunContext:
    return RunContext(run_id="run-1", session_id="session-1", user_id=user_id)


def _stash(db: Any, user_id: str, key: str) -> Dict[str, Any]:
    row = db.get_auth_token("xai", user_id, PENDING_SERVICE)
    assert row is not None, "expected a pending-login row"
    assert is_encrypted(row["token_data"])
    return decrypt_dict(row["token_data"], key=key)


# ---------------------------------------------------------------------------
# U1: construction and registration
# ---------------------------------------------------------------------------


def test_toolkit_registers_exactly_the_two_sign_in_tools(tmp_path):
    auth = XAIAuth(token_path=str(tmp_path / "token.json"), encryption_key="key-1")

    assert auth.name == "xai_auth"
    assert list(auth.functions) == ["sign_in_with_supergrok", "check_supergrok_login"]
    # The async twins register under the SAME names (they are the same two tools)
    assert list(auth.async_functions) == list(auth.functions)


def test_toolkit_builds_a_manager_from_the_constructor_pieces(tmp_path, sqlite_db):
    auth = XAIAuth(db=sqlite_db, token_path=str(tmp_path / "token.json"), encryption_key="key-1")

    assert isinstance(auth.token_manager, XAITokenManager)
    assert auth.token_manager.db is sqlite_db
    assert auth.token_manager.token_path == str(tmp_path / "token.json")
    assert auth.token_manager.encryption_key == "key-1"
    assert auth.token_manager.encrypt_tokens is True


def test_toolkit_reads_the_encryption_key_from_the_environment(monkeypatch):
    monkeypatch.setenv("XAI_TOKEN_ENCRYPTION_KEY", "env-key")

    assert XAIAuth().token_manager.encryption_key == "env-key"


def test_toolkit_uses_a_supplied_manager_as_is(endpoint, sqlite_db, encryption_key):
    manager = XAITokenManager(db=sqlite_db, encryption_key=encryption_key)
    auth = XAIAuth(token_manager=manager, db=None)

    assert auth.token_manager is manager


def test_instructions_name_both_tools_in_call_order():
    instructions = XAIAuth().instructions

    assert instructions is not None
    assert instructions.index("sign_in_with_supergrok") < instructions.index("check_supergrok_login")


# ---------------------------------------------------------------------------
# U2: tool 1 return text and the pending stash
# ---------------------------------------------------------------------------


def test_sign_in_returns_the_approval_link_and_the_user_code(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)

    payload = json.loads(auth.sign_in_with_supergrok(run_context=_ctx("u1")))

    assert payload == {"message": SIGN_IN_MESSAGE, "url": APPROVAL_URL}
    assert len(endpoint.device_requests) == 1


def test_sign_in_stashes_the_pending_login_encrypted_under_the_requester(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)

    auth.sign_in_with_supergrok(run_context=_ctx("u1"))

    stash = _stash(sqlite_db, "u1", encryption_key)
    assert stash["device_code"] == "device-code-1"
    assert stash["interval"] == 5
    # The pending row belongs to the requester, never to the deployment slot
    assert sqlite_db.get_auth_token("xai", "", PENDING_SERVICE) is None


def test_sign_in_without_a_db_stashes_the_pending_login_in_process(endpoint, tmp_path, encryption_key):
    auth = _toolkit(endpoint, token_path=str(tmp_path / "token.json"), encryption_key=encryption_key)

    auth.sign_in_with_supergrok(run_context=_ctx("u1"))

    assert auth._pending["u1"]["device_code"] == "device-code-1"


# ---------------------------------------------------------------------------
# U3: already signed in, and the force=True re-login
# ---------------------------------------------------------------------------


def test_sign_in_reports_an_existing_session_without_starting_a_new_flow(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))
    auth.check_supergrok_login(run_context=_ctx("u1"))
    device_calls = len(endpoint.device_requests)

    payload = json.loads(auth.sign_in_with_supergrok(run_context=_ctx("u1")))

    assert payload == {"message": ALREADY_SIGNED_IN}
    assert len(endpoint.device_requests) == device_calls


def test_force_signs_out_the_stored_session_then_starts_a_fresh_flow(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))
    auth.check_supergrok_login(run_context=_ctx("u1"))
    assert sqlite_db.get_auth_token(*USER_KEY) is not None

    payload = json.loads(auth.sign_in_with_supergrok(run_context=_ctx("u1"), force=True))

    assert payload == {"message": SIGN_IN_MESSAGE, "url": APPROVAL_URL}
    # sign_out() wiped the durable row before the new flow started
    assert sqlite_db.get_auth_token(*USER_KEY) is None
    assert len(endpoint.device_requests) == 2


# ---------------------------------------------------------------------------
# U4: tool 2 success
# ---------------------------------------------------------------------------


def test_check_login_stores_the_token_at_the_deployment_slot(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"message": SIGNED_IN_PER_USER}
    row = sqlite_db.get_auth_token(*USER_KEY)
    assert row is not None
    assert row["granted_scopes"] == XAI_OAUTH_SCOPE.split()
    assert decrypt_dict(row["token_data"], key=encryption_key)["access_token"] == "access-token-1"


def test_check_login_polls_once_and_clears_the_pending_row(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))

    auth.check_supergrok_login(run_context=_ctx("u1"))

    assert len(endpoint.poll_requests) == 1
    assert endpoint.poll_requests[0]["device_code"] == "device-code-1"
    assert sqlite_db.get_auth_token("xai", "u1", PENDING_SERVICE) is None


# ---------------------------------------------------------------------------
# U5: tool 2 pending - one poll per chat turn, interval carried forward
# ---------------------------------------------------------------------------


def test_check_login_reports_not_approved_yet_and_polls_exactly_once(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))
    endpoint.queue_poll(400, {"error": "authorization_pending"})

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"message": NOT_APPROVED}
    assert len(endpoint.poll_requests) == 1
    assert _stash(sqlite_db, "u1", encryption_key)["interval"] == 5


def test_a_slow_down_poll_re_stashes_the_backed_off_interval(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))
    endpoint.queue_poll(400, {"error": "slow_down"})

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"message": NOT_APPROVED}
    # RFC 8628 section 3.5 mandates +5 seconds, carried into the next turn
    assert _stash(sqlite_db, "u1", encryption_key)["interval"] == 10


def test_a_pending_turn_leaves_the_login_resumable(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))
    endpoint.queue_poll(400, {"error": "authorization_pending"})
    auth.check_supergrok_login(run_context=_ctx("u1"))

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"message": SIGNED_IN_PER_USER}
    assert len(endpoint.poll_requests) == 2
    assert sqlite_db.get_auth_token(*USER_KEY) is not None


# ---------------------------------------------------------------------------
# U6: tool 2 terminal outcomes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error_code, reason",
    [
        ("access_denied", "SuperGrok sign-in was denied in the browser"),
        ("expired_token", "The SuperGrok sign-in code expired (30 minutes). Start the login again"),
    ],
)
def test_a_terminal_poll_reports_the_reason_and_drops_the_pending_login(
    endpoint, sqlite_db, encryption_key, error_code, reason
):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))
    endpoint.queue_poll(400, {"error": error_code})

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"error": f"Sign-in failed: {reason}. Start again with sign_in_with_supergrok."}
    assert sqlite_db.get_auth_token("xai", "u1", PENDING_SERVICE) is None
    assert sqlite_db.get_auth_token(*USER_KEY) is None


def test_an_unknown_poll_error_is_reported_as_a_failed_sign_in(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))
    endpoint.queue_poll(400, {"error": "server_error"})

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    # poll_once raises on unrecognised codes; the tool never leaks the exception
    assert payload["error"].startswith("Sign-in failed: ")
    assert payload["error"].endswith("Start again with sign_in_with_supergrok.")
    assert sqlite_db.get_auth_token("xai", "u1", PENDING_SERVICE) is None


def test_a_failed_device_start_is_reported_as_json(sqlite_db, encryption_key):
    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    manager = XAITokenManager(
        db=sqlite_db,
        encryption_key=encryption_key,
        http_client=httpx.Client(transport=httpx.MockTransport(failing)),
    )
    auth = XAIAuth(token_manager=manager)

    payload = json.loads(auth.sign_in_with_supergrok(run_context=_ctx("u1")))

    assert "error" in payload
    assert sqlite_db.get_auth_token("xai", "u1", PENDING_SERVICE) is None


# ---------------------------------------------------------------------------
# U7: no sign-in in progress
# ---------------------------------------------------------------------------


def test_check_login_without_a_pending_login_says_so(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"error": NO_SIGN_IN}
    assert endpoint.poll_requests == []


def test_a_second_check_after_completion_says_no_sign_in_is_in_progress(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))
    auth.check_supergrok_login(run_context=_ctx("u1"))

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"error": NO_SIGN_IN}


def test_one_users_pending_login_is_not_visible_to_another(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u2")))

    assert payload == {"error": NO_SIGN_IN}
    assert _stash(sqlite_db, "u1", encryption_key)["device_code"] == "device-code-1"


# ---------------------------------------------------------------------------
# U8: the script user - no run_context at all
# ---------------------------------------------------------------------------


def test_the_whole_flow_works_without_a_run_context(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)

    start = json.loads(auth.sign_in_with_supergrok())
    assert start == {"message": SIGN_IN_MESSAGE, "url": APPROVAL_URL}
    # The script user degrades to the empty-string slot, like the token row itself
    assert _stash(sqlite_db, "", encryption_key)["device_code"] == "device-code-1"

    finish = json.loads(auth.check_supergrok_login())
    assert finish == {"message": SIGNED_IN}
    assert sqlite_db.get_auth_token(*STORE_KEY) is not None


def test_a_run_context_without_a_user_id_uses_the_same_empty_slot(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)

    auth.sign_in_with_supergrok(run_context=_ctx(None))

    assert _stash(sqlite_db, "", encryption_key)["device_code"] == "device-code-1"


# ---------------------------------------------------------------------------
# U9: run_context is framework-injected, never model-visible
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", ["sign_in_with_supergrok", "check_supergrok_login"])
def test_run_context_is_hidden_from_the_model_schema(tool_name):
    function = XAIAuth().functions[tool_name]
    function.process_entrypoint()

    assert "run_context" not in function.parameters["properties"]
    assert "run_context" not in function.parameters.get("required", [])


def test_force_is_model_visible_on_the_sign_in_tool():
    function = XAIAuth().functions["sign_in_with_supergrok"]
    function.process_entrypoint()

    assert "force" in function.parameters["properties"]


def test_the_framework_injects_run_context_into_the_tool(endpoint, sqlite_db, encryption_key):
    """The requester reaches the tool through injection, not through the model's arguments."""
    from agno.tools.function import FunctionCall

    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    function = auth.functions["sign_in_with_supergrok"]
    function.process_entrypoint()
    function._run_context = _ctx("injected-user")

    result = FunctionCall(function=function, arguments={}).execute()

    assert json.loads(result.result)["url"] == APPROVAL_URL
    assert _stash(sqlite_db, "injected-user", encryption_key)["device_code"] == "device-code-1"


def test_both_the_pending_row_and_the_token_row_follow_the_requester(endpoint, sqlite_db, encryption_key):
    """The two keys match: the login that started under a user finishes under them."""
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)

    auth.sign_in_with_supergrok(run_context=_ctx("u1"))
    assert _stash(sqlite_db, "u1", encryption_key)["device_code"] == "device-code-1"

    auth.check_supergrok_login(run_context=_ctx("u1"))
    assert sqlite_db.get_auth_token(*USER_KEY) is not None
    # The shared deployment slot is untouched by one user signing in
    assert sqlite_db.get_auth_token(*STORE_KEY) is None


# ---------------------------------------------------------------------------
# U10: storage refused, and the file-degrade note
# ---------------------------------------------------------------------------


def test_a_signed_in_user_is_told_when_the_token_could_not_be_saved(endpoint, sqlite_db, monkeypatch):
    monkeypatch.delenv("XAI_TOKEN_ENCRYPTION_KEY", raising=False)
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=None)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"error": NOT_SAVED}
    assert sqlite_db.get_auth_token(*USER_KEY) is None


def test_encryption_off_stores_the_token_and_reports_plain_success(endpoint, sqlite_db):
    auth = _toolkit(endpoint, db=sqlite_db, encrypt_tokens=False)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"message": SIGNED_IN_PER_USER}
    row = sqlite_db.get_auth_token(*USER_KEY)
    assert row is not None
    assert not is_encrypted(row["token_data"])


def test_a_db_without_token_storage_degrades_to_a_file_and_says_so(endpoint, tmp_path, encryption_key):
    db = MagicMock()
    db.upsert_auth_token.side_effect = NotImplementedError
    db.get_auth_token.side_effect = NotImplementedError
    db.delete_auth_token.side_effect = NotImplementedError
    auth = _toolkit(endpoint, db=db, token_path=str(tmp_path / "token.json"), encryption_key=encryption_key)
    auth.sign_in_with_supergrok()

    payload = json.loads(auth.check_supergrok_login())

    assert payload == {"message": SIGNED_IN + FILE_DEGRADE_NOTE}
    stored = json.loads((tmp_path / "token.json").read_text())
    assert decrypt_dict(stored, key=encryption_key)["access_token"] == "access-token-1"


def test_a_db_without_token_storage_keeps_a_users_token_in_memory_and_says_so(endpoint, tmp_path, encryption_key):
    """One file cannot hold one session per user, so a per-user sign-in stays in the process."""
    db = MagicMock()
    db.upsert_auth_token.side_effect = NotImplementedError
    db.get_auth_token.side_effect = NotImplementedError
    db.delete_auth_token.side_effect = NotImplementedError
    auth = _toolkit(endpoint, db=db, token_path=str(tmp_path / "token.json"), encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"message": SIGNED_IN_PER_USER + MEMORY_DEGRADE_NOTE}
    assert not (tmp_path / "token.json").exists()


def test_an_async_db_degrades_to_a_file_and_says_so(endpoint, tmp_path, encryption_key):
    """The SYNC tools cannot await an async backend, so the manager wrote a file instead."""

    class AsyncOnlyDb:
        async def get_auth_token(self, provider, user_id, service):  # pragma: no cover - never awaited
            return None

        async def upsert_auth_token(self, token):  # pragma: no cover - never awaited
            return None

        async def delete_auth_token(self, provider, user_id, service):  # pragma: no cover - never awaited
            return True

    auth = _toolkit(endpoint, db=AsyncOnlyDb(), token_path=str(tmp_path / "token.json"), encryption_key=encryption_key)
    auth.sign_in_with_supergrok()

    payload = json.loads(auth.check_supergrok_login())

    assert payload == {"message": SIGNED_IN + FILE_DEGRADE_NOTE}
    stored = json.loads((tmp_path / "token.json").read_text())
    assert decrypt_dict(stored, key=encryption_key)["access_token"] == "access-token-1"


def test_a_pending_login_survives_a_db_that_cannot_store_it(endpoint, tmp_path, encryption_key):
    db = MagicMock()
    db.upsert_auth_token.side_effect = NotImplementedError
    db.get_auth_token.side_effect = NotImplementedError
    db.delete_auth_token.side_effect = NotImplementedError
    auth = _toolkit(endpoint, db=db, token_path=str(tmp_path / "token.json"), encryption_key=encryption_key)

    auth.sign_in_with_supergrok(run_context=_ctx("u1"))

    assert auth._pending["u1"]["device_code"] == "device-code-1"


def test_a_seeded_pending_row_from_another_process_completes_the_login(
    endpoint, sqlite_db, encryption_key, device_response
):
    """The pending row is the cross-replica handoff: turn 2 may land on a fresh process."""
    sqlite_db.upsert_auth_token(
        {
            "provider": "xai",
            "user_id": "u1",
            "service": PENDING_SERVICE,
            "token_data": encrypt_dict(
                {"device_code": "device-code-1", "interval": 5},
                key=encryption_key,
            ),
            "granted_scopes": [],
        }
    )
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"message": SIGNED_IN_PER_USER}
    assert sqlite_db.get_auth_token(*USER_KEY) is not None


# ---------------------------------------------------------------------------
# U11-U16: the async tool surface
#
# The point is the cross-replica handoff (U14), not the keyword: the sync
# tools cannot await an async backend, so they stash the pending login in
# process memory - which the next turn's replica cannot see.
# ---------------------------------------------------------------------------


def _async_toolkit(endpoint: AuthEndpoint, **manager_kwargs: Any) -> XAIAuth:
    """A toolkit whose manager reaches the mock endpoint over the async transport."""
    manager = XAITokenManager(
        async_http_client=httpx.AsyncClient(transport=httpx.MockTransport(endpoint)), **manager_kwargs
    )
    return XAIAuth(token_manager=manager)


class AsyncDb:
    """An async backend: coroutine methods over a real store, as async adapters ship."""

    def __init__(self, inner: Any):
        self._inner = inner

    async def get_auth_token(self, provider: str, user_id: str, service: str) -> Any:
        return self._inner.get_auth_token(provider, user_id, service)

    async def upsert_auth_token(self, token: Dict[str, Any]) -> Any:
        return self._inner.upsert_auth_token(token)

    async def delete_auth_token(self, provider: str, user_id: str, service: str) -> Any:
        return self._inner.delete_auth_token(provider, user_id, service)


def test_no_a_prefixed_twin_name_reaches_the_model(tmp_path):
    """The a* methods exist on the class; only the two stable names are tools."""
    auth = XAIAuth(token_path=str(tmp_path / "token.json"), encryption_key="key-1")

    assert callable(auth.asign_in_with_supergrok)
    assert callable(auth.acheck_supergrok_login)
    assert set(auth.functions) | set(auth.async_functions) == {
        "sign_in_with_supergrok",
        "check_supergrok_login",
    }


def test_async_mode_selects_the_awaitable_entrypoints(tmp_path):
    """agent/_tools.py picks get_async_functions() in async mode - they must be coroutines."""
    from inspect import iscoroutinefunction

    auth = XAIAuth(token_path=str(tmp_path / "token.json"), encryption_key="key-1")

    async_functions = auth.get_async_functions()
    assert set(async_functions) == {"sign_in_with_supergrok", "check_supergrok_login"}
    assert all(iscoroutinefunction(f.entrypoint) for f in async_functions.values())
    assert not any(iscoroutinefunction(f.entrypoint) for f in auth.get_functions().values())


async def test_the_async_flow_signs_in_and_polls_exactly_once(endpoint, sqlite_db, encryption_key):
    auth = _async_toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)

    started = json.loads(await auth.asign_in_with_supergrok(run_context=_ctx("u1")))
    payload = json.loads(await auth.acheck_supergrok_login(run_context=_ctx("u1")))

    assert started == {"message": SIGN_IN_MESSAGE, "url": APPROVAL_URL}
    assert payload == {"message": SIGNED_IN_PER_USER}
    assert len(endpoint.poll_requests) == 1
    assert sqlite_db.get_auth_token(*USER_KEY) is not None
    assert sqlite_db.get_auth_token("xai", "u1", PENDING_SERVICE) is None


async def test_an_async_db_carries_the_pending_login_across_replicas(endpoint, sqlite_db, encryption_key):
    """THE REGRESSION: turn 1 and turn 2 land on different processes sharing one async db."""
    db = AsyncDb(sqlite_db)
    replica_a = _async_toolkit(endpoint, db=db, encryption_key=encryption_key)

    await replica_a.asign_in_with_supergrok(run_context=_ctx("u1"))

    # The pending login belongs to the database, not to this process
    assert replica_a._pending == {}
    assert _stash(sqlite_db, "u1", encryption_key)["device_code"] == "device-code-1"

    replica_b = _async_toolkit(endpoint, db=db, encryption_key=encryption_key)
    payload = json.loads(await replica_b.acheck_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"message": SIGNED_IN_PER_USER}
    assert sqlite_db.get_auth_token(*USER_KEY) is not None


async def test_the_async_check_reports_not_approved_yet_and_re_stashes_the_interval(
    endpoint, sqlite_db, encryption_key
):
    endpoint.queue_poll(400, {"error": "slow_down"})
    auth = _async_toolkit(endpoint, db=AsyncDb(sqlite_db), encryption_key=encryption_key)
    await auth.asign_in_with_supergrok(run_context=_ctx("u1"))

    payload = json.loads(await auth.acheck_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"message": NOT_APPROVED}
    assert _stash(sqlite_db, "u1", encryption_key)["interval"] == 10


async def test_the_async_force_signs_out_then_starts_a_fresh_login(endpoint, sqlite_db, encryption_key):
    auth = _async_toolkit(endpoint, db=AsyncDb(sqlite_db), encryption_key=encryption_key)
    await auth.asign_in_with_supergrok(run_context=_ctx("u1"))
    await auth.acheck_supergrok_login(run_context=_ctx("u1"))
    assert sqlite_db.get_auth_token(*USER_KEY) is not None

    payload = json.loads(await auth.asign_in_with_supergrok(run_context=_ctx("u1"), force=True))

    assert payload == {"message": SIGN_IN_MESSAGE, "url": APPROVAL_URL}
    assert len(endpoint.device_requests) == 2


async def test_the_async_check_without_a_pending_login_says_so(endpoint, sqlite_db, encryption_key):
    auth = _async_toolkit(endpoint, db=AsyncDb(sqlite_db), encryption_key=encryption_key)

    payload = json.loads(await auth.acheck_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"error": NO_SIGN_IN}
    assert endpoint.poll_requests == []


async def test_an_async_terminal_poll_reports_the_reason_and_drops_the_pending_login(
    endpoint, sqlite_db, encryption_key
):
    endpoint.queue_poll(400, {"error": "access_denied"})
    auth = _async_toolkit(endpoint, db=AsyncDb(sqlite_db), encryption_key=encryption_key)
    await auth.asign_in_with_supergrok(run_context=_ctx("u1"))

    payload = json.loads(await auth.acheck_supergrok_login(run_context=_ctx("u1")))

    assert payload == {
        "error": "Sign-in failed: SuperGrok sign-in was denied in the browser. Start again with sign_in_with_supergrok."
    }
    assert sqlite_db.get_auth_token("xai", "u1", PENDING_SERVICE) is None


# ---------------------------------------------------------------------------
# The per-user flip: the final token row follows the caller, like the pending row
# ---------------------------------------------------------------------------


def test_check_login_stores_the_token_under_the_caller(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"message": SIGNED_IN_PER_USER}
    assert sqlite_db.get_auth_token("xai", "u1", "supergrok") is not None
    # The deployment slot is not written by a per-user sign-in
    assert sqlite_db.get_auth_token(*STORE_KEY) is None


def test_a_script_user_still_signs_in_to_the_deployment_slot(endpoint, sqlite_db, encryption_key):
    """No run_context means no user; behaviour is byte-identical to before the flip."""
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok()

    payload = json.loads(auth.check_supergrok_login())

    assert payload == {"message": SIGNED_IN}
    assert sqlite_db.get_auth_token(*STORE_KEY) is not None


def test_one_users_session_does_not_sign_another_user_in(endpoint, sqlite_db, encryption_key):
    """Tool 1 checks the caller's row, not the deployment's."""
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))
    auth.check_supergrok_login(run_context=_ctx("u1"))

    payload = json.loads(auth.sign_in_with_supergrok(run_context=_ctx("u2")))

    # u2 gets a fresh approval link rather than "already signed in"
    assert payload == {"message": SIGN_IN_MESSAGE, "url": APPROVAL_URL}


def test_a_signed_in_user_is_told_they_are_already_signed_in(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))
    auth.check_supergrok_login(run_context=_ctx("u1"))

    payload = json.loads(auth.sign_in_with_supergrok(run_context=_ctx("u1")))

    assert payload == {"message": ALREADY_SIGNED_IN}


def test_force_signs_out_only_the_caller(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    for user in ("u1", "u2"):
        auth.sign_in_with_supergrok(run_context=_ctx(user))
        auth.check_supergrok_login(run_context=_ctx(user))

    auth.sign_in_with_supergrok(run_context=_ctx("u1"), force=True)

    assert sqlite_db.get_auth_token("xai", "u1", "supergrok") is None
    assert sqlite_db.get_auth_token("xai", "u2", "supergrok") is not None


async def test_the_async_check_stores_the_token_under_the_caller(endpoint, sqlite_db, encryption_key):
    auth = _async_toolkit(endpoint, db=AsyncDb(sqlite_db), encryption_key=encryption_key)
    await auth.asign_in_with_supergrok(run_context=_ctx("u1"))

    payload = json.loads(await auth.acheck_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"message": SIGNED_IN_PER_USER}
    assert sqlite_db.get_auth_token("xai", "u1", "supergrok") is not None


# ---------------------------------------------------------------------------
# Transport failures must not escape the tools
#
# Found live in AgentOS: xAI had authorised the device, the poll timed out, the
# exception escaped, and the model told the user their approval had not arrived.
# ---------------------------------------------------------------------------

TRANSPORT_FAILED = "Could not reach the sign-in service just now. Your approval is not lost - tell me to check again."


class FlakyEndpoint(AuthEndpoint):
    """Device grants succeed; the token endpoint times out."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == XAI_DEVICE_CODE_URL and not getattr(self, "fail_device", False):
            return super().__call__(request)
        raise httpx.ReadTimeout("simulated network timeout", request=request)


@pytest.fixture
def flaky(device_response, token_response) -> FlakyEndpoint:
    return FlakyEndpoint(device_response, token_response)


def test_a_poll_timeout_is_reported_as_json_not_raised(flaky, sqlite_db, encryption_key):
    auth = _toolkit(flaky, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"error": TRANSPORT_FAILED}


def test_a_poll_timeout_keeps_the_login_resumable(flaky, sqlite_db, encryption_key):
    """The approval is not lost: the pending row must survive so a retry works."""
    auth = _toolkit(flaky, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))

    auth.check_supergrok_login(run_context=_ctx("u1"))

    assert _stash(sqlite_db, "u1", encryption_key)["device_code"] == "device-code-1"


def test_a_device_start_timeout_is_reported_as_json_not_raised(flaky, sqlite_db, encryption_key):
    flaky.fail_device = True
    auth = _toolkit(flaky, db=sqlite_db, encryption_key=encryption_key)

    payload = json.loads(auth.sign_in_with_supergrok(run_context=_ctx("u1")))

    assert payload == {"error": TRANSPORT_FAILED}


async def test_the_async_poll_timeout_is_reported_as_json_not_raised(flaky, sqlite_db, encryption_key):
    auth = _async_toolkit(flaky, db=AsyncDb(sqlite_db), encryption_key=encryption_key)
    await auth.asign_in_with_supergrok(run_context=_ctx("u1"))

    payload = json.loads(await auth.acheck_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"error": TRANSPORT_FAILED}
    assert _stash(sqlite_db, "u1", encryption_key)["device_code"] == "device-code-1"


async def test_the_async_device_start_timeout_is_reported_as_json_not_raised(flaky, sqlite_db, encryption_key):
    flaky.fail_device = True
    auth = _async_toolkit(flaky, db=AsyncDb(sqlite_db), encryption_key=encryption_key)

    payload = json.loads(await auth.asign_in_with_supergrok(run_context=_ctx("u1")))

    assert payload == {"error": TRANSPORT_FAILED}


def test_a_failed_device_start_leaves_the_existing_session_intact(tmp_path, encryption_key):
    """force=True must not wipe a working session before the new login exists."""

    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("device endpoint unreachable")

    path = tmp_path / "token.json"
    manager = XAITokenManager(
        encrypt_tokens=False,
        token_path=str(path),
        http_client=httpx.Client(transport=httpx.MockTransport(unreachable)),
    )
    manager._save({"access_token": "deployment-token", "expires_at": 9_999_999_999}, user_id="")
    auth = XAIAuth(token_manager=manager)

    payload = json.loads(auth.sign_in_with_supergrok(force=True))

    assert "error" in payload
    assert path.exists()


# ---------------------------------------------------------------------------
# A pending-login write that FAILS must not look like one that succeeded
# ---------------------------------------------------------------------------


class _FailingUpsertDb:
    """Storage is reachable, but this write fails.

    agno adapters swallow their own errors and report failure by returning None
    (SqliteDb.upsert_auth_token does exactly this), which the token manager
    already checks for.
    """

    def __init__(self, inner: Any):
        self._inner = inner

    def get_auth_token(self, provider: str, user_id: str, service: str) -> Any:
        return self._inner.get_auth_token(provider, user_id, service)

    def upsert_auth_token(self, token: Dict[str, Any]) -> Any:
        # Only the pending write fails; the token row still stores, so the reply
        # is the plain success message and the assertion stays contract-exact.
        if token["service"] == PENDING_SERVICE:
            return None
        return self._inner.upsert_auth_token(token)

    def delete_auth_token(self, provider: str, user_id: str, service: str) -> Any:
        return self._inner.delete_auth_token(provider, user_id, service)


def test_a_failed_pending_write_keeps_the_login_recoverable(endpoint, sqlite_db, encryption_key):
    """The user approves the link either way; the next turn must still finish it."""
    auth = _toolkit(endpoint, db=_FailingUpsertDb(sqlite_db), encryption_key=encryption_key)

    auth.sign_in_with_supergrok(run_context=_ctx("u1"))
    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"message": SIGNED_IN_PER_USER}


@pytest.mark.asyncio
async def test_a_failed_async_pending_write_keeps_the_login_recoverable(endpoint, sqlite_db, encryption_key):
    """Async twin: the same write failure, the same recovery."""
    auth = _async_toolkit(endpoint, db=AsyncDb(_FailingUpsertDb(sqlite_db)), encryption_key=encryption_key)

    await auth.asign_in_with_supergrok(run_context=_ctx("u1"))
    payload = json.loads(await auth.acheck_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"message": SIGNED_IN_PER_USER}


def test_a_failed_pending_write_does_not_leave_a_stale_row_behind(endpoint, sqlite_db, encryption_key):
    """Memory holds the fresh device code, but _read_pending reads the database first."""

    class _FailsAfterFirstPendingWrite:
        def __init__(self, inner: Any):
            self._inner = inner
            self.pending_writes = 0

        def get_auth_token(self, provider: str, user_id: str, service: str) -> Any:
            return self._inner.get_auth_token(provider, user_id, service)

        def delete_auth_token(self, provider: str, user_id: str, service: str) -> Any:
            return self._inner.delete_auth_token(provider, user_id, service)

        def upsert_auth_token(self, token: Dict[str, Any]) -> Any:
            if token["service"] == PENDING_SERVICE:
                self.pending_writes += 1
                if self.pending_writes > 1:
                    return None
            return self._inner.upsert_auth_token(token)

    auth = _toolkit(endpoint, db=_FailsAfterFirstPendingWrite(sqlite_db), encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))

    # The second grant is a DIFFERENT device code; its write fails, so it lives in memory
    endpoint.device_json = {**endpoint.device_json, "device_code": "device-code-2", "user_code": "WXYZ-9999"}
    shown = json.loads(auth.sign_in_with_supergrok(run_context=_ctx("u1"), force=True))
    auth.check_supergrok_login(run_context=_ctx("u1"))

    # The poll must use the code the user was just shown, not the persisted older one
    assert "WXYZ-9999" in shown["message"]
    assert endpoint.poll_requests[-1]["device_code"] == "device-code-2"
