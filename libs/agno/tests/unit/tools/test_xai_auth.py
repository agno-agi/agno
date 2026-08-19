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
from agno.tools.xai_auth import XAIAuth

from agno.models.xai.oauth import XAI_DEVICE_CODE_URL, XAI_OAUTH_SCOPE, XAITokenManager
from agno.run import RunContext
from agno.utils.encryption import decrypt_dict, encrypt_dict, generate_encryption_key, is_encrypted

STORE_KEY = ("xai", "", "supergrok")
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
NOT_APPROVED = "Not approved yet. Open the link, approve the sign-in, then tell me again when you're done."
NO_SIGN_IN = "No sign-in is in progress. Call sign_in_with_supergrok first."
NOT_SAVED = (
    "Signed in, but the token was NOT saved: XAI_TOKEN_ENCRYPTION_KEY is not set. "
    "Set it (see the cookbook) and sign in again, or pass encrypt_tokens=False for local dev."
)
FILE_DEGRADE_NOTE = " (Note: token stored to a local file — this database does not support token storage.)"


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
    assert auth.async_functions == {}


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
    assert stash["deadline"] > 0
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
    assert sqlite_db.get_auth_token(*STORE_KEY) is not None

    payload = json.loads(auth.sign_in_with_supergrok(run_context=_ctx("u1"), force=True))

    assert payload == {"message": SIGN_IN_MESSAGE, "url": APPROVAL_URL}
    # sign_out() wiped the durable row before the new flow started
    assert sqlite_db.get_auth_token(*STORE_KEY) is None
    assert len(endpoint.device_requests) == 2


# ---------------------------------------------------------------------------
# U4: tool 2 success
# ---------------------------------------------------------------------------


def test_check_login_stores_the_token_at_the_deployment_slot(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"message": SIGNED_IN}
    row = sqlite_db.get_auth_token(*STORE_KEY)
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

    assert payload == {"message": SIGNED_IN}
    assert len(endpoint.poll_requests) == 2
    assert sqlite_db.get_auth_token(*STORE_KEY) is not None


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
    assert sqlite_db.get_auth_token(*STORE_KEY) is None


def test_an_unknown_poll_error_is_reported_as_a_failed_sign_in(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))
    endpoint.queue_poll(400, {"error": "server_error"})

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    # poll_once raises on unrecognised codes; the tool never leaks the exception
    assert payload["error"].startswith("Sign-in failed: ")
    assert payload["error"].endswith("Start again with sign_in_with_supergrok.")
    assert sqlite_db.get_auth_token("xai", "u1", PENDING_SERVICE) is None


def test_a_failed_device_start_is_reported_as_json(sqlite_db, encryption_key, token_response, device_response):
    endpoint = AuthEndpoint(device_response, token_response)

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


def test_the_pending_row_follows_the_requester_while_the_token_row_stays_shared(endpoint, sqlite_db, encryption_key):
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)

    auth.sign_in_with_supergrok(run_context=_ctx("u1"))
    assert _stash(sqlite_db, "u1", encryption_key)["device_code"] == "device-code-1"

    auth.check_supergrok_login(run_context=_ctx("u1"))
    # PR 2 provisions the deployment credential; per-user resolution lands later
    assert sqlite_db.get_auth_token(*STORE_KEY) is not None
    assert sqlite_db.get_auth_token("xai", "u1", "supergrok") is None


# ---------------------------------------------------------------------------
# U10: storage refused, and the file-degrade note
# ---------------------------------------------------------------------------


def test_a_signed_in_user_is_told_when_the_token_could_not_be_saved(endpoint, sqlite_db, monkeypatch):
    monkeypatch.delenv("XAI_TOKEN_ENCRYPTION_KEY", raising=False)
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=None)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"error": NOT_SAVED}
    assert sqlite_db.get_auth_token(*STORE_KEY) is None


def test_encryption_off_stores_the_token_and_reports_plain_success(endpoint, sqlite_db):
    auth = _toolkit(endpoint, db=sqlite_db, encrypt_tokens=False)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"message": SIGNED_IN}
    row = sqlite_db.get_auth_token(*STORE_KEY)
    assert row is not None
    assert not is_encrypted(row["token_data"])


def test_a_db_without_token_storage_degrades_to_a_file_and_says_so(endpoint, tmp_path, encryption_key):
    db = MagicMock()
    db.upsert_auth_token.side_effect = NotImplementedError
    db.get_auth_token.side_effect = NotImplementedError
    db.delete_auth_token.side_effect = NotImplementedError
    auth = _toolkit(endpoint, db=db, token_path=str(tmp_path / "token.json"), encryption_key=encryption_key)
    auth.sign_in_with_supergrok(run_context=_ctx("u1"))

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

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
                {"device_code": "device-code-1", "interval": 5, "deadline": 1_000_000.0},
                key=encryption_key,
            ),
            "granted_scopes": [],
        }
    )
    auth = _toolkit(endpoint, db=sqlite_db, encryption_key=encryption_key)

    payload = json.loads(auth.check_supergrok_login(run_context=_ctx("u1")))

    assert payload == {"message": SIGNED_IN}
    assert sqlite_db.get_auth_token(*STORE_KEY) is not None
