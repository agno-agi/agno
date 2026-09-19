import asyncio
import base64
import hashlib
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agno.tools.atomic_mail import AtomicMailTools


def _fake_jwt(payload: dict) -> str:
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"header.{payload_b64}.signature"


def _response(headers=None, json_data=None, text="{}"):
    response = MagicMock()
    response.headers = headers or {}
    response.raise_for_status.return_value = None
    response.json.return_value = json_data
    response.text = text
    return response


CHALLENGE_JWT = _fake_jwt({"jti": "challenge-123", "difficulty": 0})
SESSION_JWT = _fake_jwt({"sub": "session"})
# The capability JWT carries the inbox local-part and the allowed sending domain
# separately; the full address is `<inboxId>@<allowedFromDomain>`.
CAPABILITY_JWT = _fake_jwt({"inboxId": "agno-agent", "allowedFromDomain": "atomicmail.ai", "exp": 9999999999})

CHALLENGE_RESPONSE = _response(headers={"Authorization": f"Bearer {CHALLENGE_JWT}"})
SESSION_RESPONSE = _response(
    headers={"Authorization": f"Bearer {SESSION_JWT}"},
    json_data={"apiKey": "atomic-api-key"},
    text='{"apiKey": "atomic-api-key"}',
)
CAPABILITY_RESPONSE = _response(headers={"Authorization": f"Bearer {CAPABILITY_JWT}"})
WELL_KNOWN_RESPONSE = _response(
    json_data={
        "apiUrl": "https://api.atomicmail.ai/jmap",
        "primaryAccounts": {"urn:ietf:params:jmap:mail": "account-1"},
    }
)
MAILBOX_QUERY_RESPONSE = _response(json_data={"methodResponses": [["Mailbox/query", {"ids": ["mailbox-inbox"]}, "m0"]]})


def test_initialization_registers_sync_and_async_tools(tmp_path):
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    assert tools.name == "atomic_mail_tools"
    assert set(tools.functions) == {"register_inbox", "send_email", "list_inbox"}
    assert set(tools.async_functions) == set(tools.functions)


def test_disabled_tool_is_not_registered(tmp_path):
    tools = AtomicMailTools(credentials_dir=str(tmp_path), enable_send_email=False)

    assert "send_email" not in tools.functions
    assert "send_email" not in tools.async_functions
    assert "register_inbox" in tools.functions
    assert "list_inbox" in tools.functions


def test_credentials_dir_from_environment(tmp_path):
    with patch.dict("os.environ", {"ATOMIC_MAIL_CREDENTIALS_DIR": str(tmp_path)}):
        tools = AtomicMailTools()

    assert tools.credentials_path == tmp_path / "credentials.json"


def test_register_inbox_rejects_invalid_username_length(tmp_path):
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = tools.register_inbox("abc")

    assert result == {"error": "username must be 5-21 characters"}


@patch("agno.tools.atomic_mail.httpx.Client")
def test_register_inbox_success_saves_credentials(mock_client_class, tmp_path):
    client = mock_client_class.return_value.__enter__.return_value
    client.post.side_effect = [CHALLENGE_RESPONSE, SESSION_RESPONSE, CAPABILITY_RESPONSE]
    client.get.return_value = WELL_KNOWN_RESPONSE
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = tools.register_inbox("agno-agent")

    assert result == {"inbox": "agno-agent@atomicmail.ai", "account_id": "account-1", "idempotent": False}
    saved = json.loads((tmp_path / "credentials.json").read_text())
    assert saved == {
        "api_key": "atomic-api-key",
        "inbox": "agno-agent@atomicmail.ai",
        "account_id": "account-1",
    }


@patch("agno.tools.atomic_mail.httpx.Client")
def test_register_inbox_is_idempotent_for_same_username(mock_client_class, tmp_path):
    (tmp_path / "credentials.json").write_text(
        json.dumps({"api_key": "existing-key", "inbox": "agno-agent@atomicmail.ai", "account_id": "account-1"})
    )
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = tools.register_inbox("agno-agent")

    assert result == {"inbox": "agno-agent@atomicmail.ai", "account_id": "account-1", "idempotent": True}
    mock_client_class.assert_not_called()


@patch("agno.tools.atomic_mail.httpx.Client")
def test_register_inbox_refuses_different_username_without_forced(mock_client_class, tmp_path):
    (tmp_path / "credentials.json").write_text(
        json.dumps({"api_key": "existing-key", "inbox": "old-agent@atomicmail.ai", "account_id": "account-1"})
    )
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = tools.register_inbox("new-agent")

    assert "error" in result
    assert "old-agent@atomicmail.ai" in result["error"]
    mock_client_class.assert_not_called()


@patch("agno.tools.atomic_mail.httpx.Client")
def test_register_inbox_http_error_returns_error_dict(mock_client_class, tmp_path):
    request = httpx.Request("POST", "https://auth.atomicmail.ai/api/v1/challenge")
    failing_response = MagicMock(spec=httpx.Response)
    failing_response.status_code = 503
    failing_response.text = "service unavailable"
    failing_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "service unavailable", request=request, response=failing_response
    )
    client = mock_client_class.return_value.__enter__.return_value
    client.post.return_value = failing_response
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = tools.register_inbox("agno-agent")

    assert result == {"error": "AtomicMail registration failed: 503 service unavailable"}


@patch("agno.tools.atomic_mail.httpx.Client")
def test_send_email_without_registered_inbox_returns_error(mock_client_class, tmp_path):
    client = mock_client_class.return_value.__enter__.return_value
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = tools.send_email(to="someone@example.com", subject="Hi", body="Hello there")

    assert result == {"error": "No AtomicMail inbox registered yet. Call register_inbox first."}
    client.post.assert_not_called()


@patch("agno.tools.atomic_mail.httpx.Client")
def test_send_email_success(mock_client_class, tmp_path):
    (tmp_path / "credentials.json").write_text(
        json.dumps({"api_key": "atomic-api-key", "inbox": "agno-agent@atomicmail.ai", "account_id": "account-1"})
    )
    email_set_response = _response(
        json_data={
            "methodResponses": [
                ["Email/set", {"created": {"draft": {"id": "email-1"}}}, "c0"],
                ["EmailSubmission/set", {"created": {"submission": {"id": "sub-1"}}}, "c1"],
            ]
        }
    )
    client = mock_client_class.return_value.__enter__.return_value
    client.post.side_effect = [
        CHALLENGE_RESPONSE,
        SESSION_RESPONSE,
        CAPABILITY_RESPONSE,
        MAILBOX_QUERY_RESPONSE,
        email_set_response,
    ]
    client.get.return_value = WELL_KNOWN_RESPONSE
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = tools.send_email(to="someone@example.com", subject="Hi", body="Hello there")

    assert result == {
        "email_id": "email-1",
        "submission_id": "sub-1",
        "to": "someone@example.com",
        "subject": "Hi",
    }


@patch("agno.tools.atomic_mail.httpx.Client")
def test_send_email_uses_full_from_address_and_identity(mock_client_class, tmp_path):
    """Guard against the `forbiddenFrom` regression: the JMAP draft must use the full
    `<local-part>@<domain>` from-address, and the submission must carry an identityId."""
    (tmp_path / "credentials.json").write_text(
        json.dumps({"api_key": "atomic-api-key", "inbox": "agno-agent@atomicmail.ai", "account_id": "account-1"})
    )
    email_set_response = _response(
        json_data={
            "methodResponses": [
                ["Email/set", {"created": {"draft": {"id": "email-1"}}}, "c0"],
                ["EmailSubmission/set", {"created": {"submission": {"id": "sub-1"}}}, "c1"],
            ]
        }
    )
    client = mock_client_class.return_value.__enter__.return_value
    client.post.side_effect = [
        CHALLENGE_RESPONSE,
        SESSION_RESPONSE,
        CAPABILITY_RESPONSE,
        MAILBOX_QUERY_RESPONSE,
        email_set_response,
    ]
    client.get.return_value = WELL_KNOWN_RESPONSE
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    tools.send_email(to="someone@example.com", subject="Hi", body="Hello there")

    # The final POST is the JMAP Email/set + EmailSubmission/set call.
    jmap_body = client.post.call_args_list[-1].kwargs["json"]
    email_set = next(call for call in jmap_body["methodCalls"] if call[0] == "Email/set")
    submission = next(call for call in jmap_body["methodCalls"] if call[0] == "EmailSubmission/set")

    draft = email_set[1]["create"]["draft"]
    assert draft["from"] == [{"email": "agno-agent@atomicmail.ai"}]
    assert "@" in draft["from"][0]["email"]

    submission_create = submission[1]["create"]["submission"]
    assert submission_create["identityId"] == "account-1"
    assert submission_create["envelope"]["mailFrom"] == {"email": "agno-agent@atomicmail.ai"}


@patch("agno.tools.atomic_mail.httpx.Client")
def test_send_email_reports_error_when_submission_fails(mock_client_class, tmp_path):
    """The draft may be created while the submission fails at the method level (an
    ["error", ...] response). That must be reported as an error, not a false success."""
    (tmp_path / "credentials.json").write_text(
        json.dumps({"api_key": "atomic-api-key", "inbox": "agno-agent@atomicmail.ai", "account_id": "account-1"})
    )
    email_set_response = _response(
        json_data={
            "methodResponses": [
                ["Email/set", {"created": {"draft": {"id": "email-1"}}}, "c0"],
                ["error", {"type": "forbiddenFrom"}, "c1"],
            ]
        }
    )
    client = mock_client_class.return_value.__enter__.return_value
    client.post.side_effect = [
        CHALLENGE_RESPONSE,
        SESSION_RESPONSE,
        CAPABILITY_RESPONSE,
        MAILBOX_QUERY_RESPONSE,
        email_set_response,
    ]
    client.get.return_value = WELL_KNOWN_RESPONSE
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = tools.send_email(to="someone@example.com", subject="Hi", body="Hello there")

    assert result["error"] == "AtomicMail rejected the email"


@patch("agno.tools.atomic_mail.httpx.Client")
def test_send_email_returns_error_on_malformed_jmap_session(mock_client_class, tmp_path):
    """A 200-OK but malformed JMAP session (missing primaryAccounts) must return a
    structured error rather than letting a KeyError escape the tool."""
    (tmp_path / "credentials.json").write_text(
        json.dumps({"api_key": "atomic-api-key", "inbox": "agno-agent@atomicmail.ai", "account_id": "account-1"})
    )
    client = mock_client_class.return_value.__enter__.return_value
    client.post.side_effect = [CHALLENGE_RESPONSE, SESSION_RESPONSE, CAPABILITY_RESPONSE]
    client.get.return_value = _response(json_data={"apiUrl": "https://api.atomicmail.ai/jmap"})
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = tools.send_email(to="someone@example.com", subject="Hi", body="Hello there")

    assert "error" in result
    assert "AtomicMail request failed" in result["error"]


@patch("agno.tools.atomic_mail.httpx.Client")
def test_list_inbox_success(mock_client_class, tmp_path):
    (tmp_path / "credentials.json").write_text(
        json.dumps({"api_key": "atomic-api-key", "inbox": "agno-agent@atomicmail.ai", "account_id": "account-1"})
    )
    email_get_response = _response(
        json_data={
            "methodResponses": [
                ["Email/query", {"ids": ["email-1"]}, "q0"],
                [
                    "Email/get",
                    {
                        "list": [
                            {
                                "id": "email-1",
                                "from": [{"email": "someone@example.com"}],
                                "to": [{"email": "agno-agent@atomicmail.ai"}],
                                "subject": "Hi",
                                "receivedAt": "2026-07-23T00:00:00Z",
                                "preview": "Hello there",
                            }
                        ]
                    },
                    "g0",
                ],
            ]
        }
    )
    client = mock_client_class.return_value.__enter__.return_value
    client.post.side_effect = [
        CHALLENGE_RESPONSE,
        SESSION_RESPONSE,
        CAPABILITY_RESPONSE,
        MAILBOX_QUERY_RESPONSE,
        email_get_response,
    ]
    client.get.return_value = WELL_KNOWN_RESPONSE
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = tools.list_inbox(limit=10)

    assert result == {
        "inbox": "agno-agent@atomicmail.ai",
        "count": 1,
        "emails": [
            {
                "id": "email-1",
                "from": [{"email": "someone@example.com"}],
                "to": [{"email": "agno-agent@atomicmail.ai"}],
                "subject": "Hi",
                "received_at": "2026-07-23T00:00:00Z",
                "preview": "Hello there",
            }
        ],
    }


# -- async tool variants -------------------------------------------------------------


@pytest.mark.asyncio
@patch("agno.tools.atomic_mail.httpx.AsyncClient")
async def test_aregister_inbox_success_saves_credentials(mock_client_class, tmp_path):
    client = mock_client_class.return_value.__aenter__.return_value
    client.post = AsyncMock(side_effect=[CHALLENGE_RESPONSE, SESSION_RESPONSE, CAPABILITY_RESPONSE])
    client.get = AsyncMock(return_value=WELL_KNOWN_RESPONSE)
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = await tools.aregister_inbox("agno-agent")

    assert result == {"inbox": "agno-agent@atomicmail.ai", "account_id": "account-1", "idempotent": False}
    saved = json.loads((tmp_path / "credentials.json").read_text())
    assert saved == {
        "api_key": "atomic-api-key",
        "inbox": "agno-agent@atomicmail.ai",
        "account_id": "account-1",
    }


@pytest.mark.asyncio
async def test_aregister_inbox_rejects_invalid_username_length(tmp_path):
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = await tools.aregister_inbox("abc")

    assert result == {"error": "username must be 5-21 characters"}


@pytest.mark.asyncio
@patch("agno.tools.atomic_mail.httpx.AsyncClient")
async def test_aregister_inbox_is_idempotent_for_same_username(mock_client_class, tmp_path):
    (tmp_path / "credentials.json").write_text(
        json.dumps({"api_key": "existing-key", "inbox": "agno-agent@atomicmail.ai", "account_id": "account-1"})
    )
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = await tools.aregister_inbox("agno-agent")

    assert result == {"inbox": "agno-agent@atomicmail.ai", "account_id": "account-1", "idempotent": True}
    mock_client_class.assert_not_called()


@pytest.mark.asyncio
@patch("agno.tools.atomic_mail.httpx.AsyncClient")
async def test_asend_email_without_registered_inbox_returns_error(mock_client_class, tmp_path):
    client = mock_client_class.return_value.__aenter__.return_value
    client.post = AsyncMock()
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = await tools.asend_email(to="someone@example.com", subject="Hi", body="Hello there")

    assert result == {"error": "No AtomicMail inbox registered yet. Call register_inbox first."}
    client.post.assert_not_awaited()


@pytest.mark.asyncio
@patch("agno.tools.atomic_mail.httpx.AsyncClient")
async def test_asend_email_success(mock_client_class, tmp_path):
    (tmp_path / "credentials.json").write_text(
        json.dumps({"api_key": "atomic-api-key", "inbox": "agno-agent@atomicmail.ai", "account_id": "account-1"})
    )
    email_set_response = _response(
        json_data={
            "methodResponses": [
                ["Email/set", {"created": {"draft": {"id": "email-1"}}}, "c0"],
                ["EmailSubmission/set", {"created": {"submission": {"id": "sub-1"}}}, "c1"],
            ]
        }
    )
    client = mock_client_class.return_value.__aenter__.return_value
    client.post = AsyncMock(
        side_effect=[
            CHALLENGE_RESPONSE,
            SESSION_RESPONSE,
            CAPABILITY_RESPONSE,
            MAILBOX_QUERY_RESPONSE,
            email_set_response,
        ]
    )
    client.get = AsyncMock(return_value=WELL_KNOWN_RESPONSE)
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = await tools.asend_email(to="someone@example.com", subject="Hi", body="Hello there")

    assert result == {
        "email_id": "email-1",
        "submission_id": "sub-1",
        "to": "someone@example.com",
        "subject": "Hi",
    }


@pytest.mark.asyncio
@patch("agno.tools.atomic_mail.httpx.AsyncClient")
async def test_alist_inbox_success(mock_client_class, tmp_path):
    (tmp_path / "credentials.json").write_text(
        json.dumps({"api_key": "atomic-api-key", "inbox": "agno-agent@atomicmail.ai", "account_id": "account-1"})
    )
    email_get_response = _response(
        json_data={
            "methodResponses": [
                ["Email/query", {"ids": ["email-1"]}, "q0"],
                [
                    "Email/get",
                    {
                        "list": [
                            {
                                "id": "email-1",
                                "from": [{"email": "someone@example.com"}],
                                "to": [{"email": "agno-agent@atomicmail.ai"}],
                                "subject": "Hi",
                                "receivedAt": "2026-07-23T00:00:00Z",
                                "preview": "Hello there",
                            }
                        ]
                    },
                    "g0",
                ],
            ]
        }
    )
    client = mock_client_class.return_value.__aenter__.return_value
    client.post = AsyncMock(
        side_effect=[
            CHALLENGE_RESPONSE,
            SESSION_RESPONSE,
            CAPABILITY_RESPONSE,
            MAILBOX_QUERY_RESPONSE,
            email_get_response,
        ]
    )
    client.get = AsyncMock(return_value=WELL_KNOWN_RESPONSE)
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = await tools.alist_inbox(limit=10)

    assert result == {
        "inbox": "agno-agent@atomicmail.ai",
        "count": 1,
        "emails": [
            {
                "id": "email-1",
                "from": [{"email": "someone@example.com"}],
                "to": [{"email": "agno-agent@atomicmail.ai"}],
                "subject": "Hi",
                "received_at": "2026-07-23T00:00:00Z",
                "preview": "Hello there",
            }
        ],
    }


# -- review-hardening regression tests -----------------------------------------------


@patch("agno.tools.atomic_mail.httpx.Client")
def test_register_inbox_does_not_overwrite_corrupt_credentials(mock_client_class, tmp_path):
    """A present-but-unreadable credentials file must not be treated as "nothing
    registered" and silently replaced by a fresh signup (which discards the live
    api_key). It must surface an error and leave the file untouched."""
    creds = tmp_path / "credentials.json"
    creds.write_text('{"api_key": "live-key", "inbox": "agno-agent@atomi')  # truncated JSON
    original = creds.read_text()
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = tools.register_inbox("new-agent")

    assert "error" in result
    assert "could not be read" in result["error"]
    assert creds.read_text() == original  # left intact, not overwritten
    mock_client_class.assert_not_called()  # no signup was attempted


def test_solve_pow_is_bounded_by_pow_timeout():
    """The nonce grind is driven by an unverified, server-set difficulty, so an
    implausibly high value must hit the wall-clock bound instead of hanging forever."""
    with pytest.raises(ValueError, match="did not converge"):
        AtomicMailTools._solve_pow("challenge", difficulty=255, max_seconds=0.0)


@patch("agno.tools.atomic_mail.httpx.Client")
def test_register_inbox_pow_timeout_returns_error(mock_client_class, tmp_path):
    """A too-hard proof-of-work challenge surfaces as a structured error, not a hang."""
    hard_challenge = _fake_jwt({"jti": "challenge-hard", "difficulty": 255})
    client = mock_client_class.return_value.__enter__.return_value
    client.post.return_value = _response(headers={"Authorization": f"Bearer {hard_challenge}"})
    tools = AtomicMailTools(credentials_dir=str(tmp_path), pow_timeout=0.0)

    result = tools.register_inbox("agno-agent")

    assert "error" in result
    assert "proof-of-work" in result["error"]


@patch("agno.tools.atomic_mail.httpx.Client")
def test_register_inbox_errors_when_capability_lacks_inbox_id(mock_client_class, tmp_path):
    """If the capability JWT carries no inboxId, registration must fail loudly rather
    than persisting inbox=None, which wedges every later call behind a forced=True that
    would then throw away the api_key of the inbox that was actually created."""
    capability_without_inbox = _fake_jwt({"allowedFromDomain": "atomicmail.ai", "exp": 9999999999})
    capability_response = _response(headers={"Authorization": f"Bearer {capability_without_inbox}"})
    client = mock_client_class.return_value.__enter__.return_value
    client.post.side_effect = [CHALLENGE_RESPONSE, SESSION_RESPONSE, capability_response]
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = tools.register_inbox("agno-agent")

    assert result == {"error": "AtomicMail signup did not return an inbox address."}
    assert not (tmp_path / "credentials.json").exists()


@patch("agno.tools.atomic_mail.httpx.Client")
def test_register_inbox_persists_inbox_even_if_account_lookup_fails(mock_client_class, tmp_path):
    """The inbox exists the moment signup authenticates. If the follow-up JMAP session
    lookup (only used to enrich account_id) fails, the api_key must still be saved and
    registration must still succeed rather than stranding a taken-but-unsaved inbox."""
    client = mock_client_class.return_value.__enter__.return_value
    client.post.side_effect = [CHALLENGE_RESPONSE, SESSION_RESPONSE, CAPABILITY_RESPONSE]
    client.get.side_effect = httpx.ConnectError("network down")
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = tools.register_inbox("agno-agent")

    assert result == {"inbox": "agno-agent@atomicmail.ai", "account_id": None, "idempotent": False}
    saved = json.loads((tmp_path / "credentials.json").read_text())
    assert saved == {"api_key": "atomic-api-key", "inbox": "agno-agent@atomicmail.ai", "account_id": None}


@patch("agno.tools.atomic_mail.httpx.Client")
def test_register_inbox_non_jwt_bearer_returns_error(mock_client_class, tmp_path):
    """A malformed (non-JWT) bearer token yields a structured error instead of an
    IndexError escaping the tool — send_email/list_inbox already handled this class."""
    client = mock_client_class.return_value.__enter__.return_value
    client.post.return_value = _response(headers={"Authorization": "Bearer not-a-jwt"})
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = tools.register_inbox("agno-agent")

    assert "error" in result
    assert "registration failed" in result["error"].lower()


@patch("agno.tools.atomic_mail.httpx.Client")
def test_send_email_unexpected_jmap_body_returns_error(mock_client_class, tmp_path):
    """A 200 whose body lacks `methodResponses` must return an error dict, not let a
    KeyError escape from the result parser that ran outside the try."""
    (tmp_path / "credentials.json").write_text(
        json.dumps({"api_key": "atomic-api-key", "inbox": "agno-agent@atomicmail.ai", "account_id": "account-1"})
    )
    unexpected = _response(json_data={"unexpected": "shape"})
    client = mock_client_class.return_value.__enter__.return_value
    client.post.side_effect = [
        CHALLENGE_RESPONSE,
        SESSION_RESPONSE,
        CAPABILITY_RESPONSE,
        MAILBOX_QUERY_RESPONSE,
        unexpected,
    ]
    client.get.return_value = WELL_KNOWN_RESPONSE
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = tools.send_email(to="someone@example.com", subject="Hi", body="Hello there")

    assert "error" in result
    assert "AtomicMail request failed" in result["error"]


def test_async_register_tool_schema_carries_param_descriptions(tmp_path):
    """get_async_functions() prefers the async variant, so its docstring must keep the
    Args block or async agents get description-less tool parameters."""
    tools = AtomicMailTools(credentials_dir=str(tmp_path))
    fn = tools.get_async_functions()["register_inbox"]
    fn.process_entrypoint()

    username = fn.parameters["properties"]["username"]
    assert username.get("description")
    assert "5-21" in username["description"]


@pytest.mark.asyncio
@patch("agno.tools.atomic_mail.httpx.AsyncClient")
async def test_aregister_inbox_offloads_pow_to_thread(mock_client_class, tmp_path):
    """The async path must run the CPU-bound scrypt solve off the event loop."""
    client = mock_client_class.return_value.__aenter__.return_value
    client.post = AsyncMock(side_effect=[CHALLENGE_RESPONSE, SESSION_RESPONSE, CAPABILITY_RESPONSE])
    client.get = AsyncMock(return_value=WELL_KNOWN_RESPONSE)
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    with patch("agno.tools.atomic_mail.asyncio.to_thread", wraps=asyncio.to_thread) as to_thread_spy:
        result = await tools.aregister_inbox("agno-agent")

    assert result["inbox"] == "agno-agent@atomicmail.ai"
    assert to_thread_spy.called
    assert to_thread_spy.call_args.args[0] == tools._solve_pow  # the solve was offloaded


@pytest.mark.asyncio
@patch("agno.tools.atomic_mail.httpx.AsyncClient")
async def test_aregister_inbox_refuses_different_username_without_forced(mock_client_class, tmp_path):
    (tmp_path / "credentials.json").write_text(
        json.dumps({"api_key": "existing-key", "inbox": "old-agent@atomicmail.ai", "account_id": "account-1"})
    )
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = await tools.aregister_inbox("new-agent")

    assert "error" in result
    assert "old-agent@atomicmail.ai" in result["error"]
    mock_client_class.assert_not_called()


@pytest.mark.asyncio
@patch("agno.tools.atomic_mail.httpx.AsyncClient")
async def test_aregister_inbox_http_error_returns_error_dict(mock_client_class, tmp_path):
    request = httpx.Request("POST", "https://auth.atomicmail.ai/api/v1/challenge")
    failing_response = MagicMock(spec=httpx.Response)
    failing_response.status_code = 503
    failing_response.text = "service unavailable"
    failing_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "service unavailable", request=request, response=failing_response
    )
    client = mock_client_class.return_value.__aenter__.return_value
    client.post = AsyncMock(return_value=failing_response)
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = await tools.aregister_inbox("agno-agent")

    assert result == {"error": "AtomicMail registration failed: 503 service unavailable"}


@pytest.mark.asyncio
@patch("agno.tools.atomic_mail.httpx.AsyncClient")
async def test_asend_email_returns_error_on_malformed_jmap_session(mock_client_class, tmp_path):
    """Async counterpart of the sync malformed-session guard: a 200 session missing
    primaryAccounts must return a structured error, not an escaping KeyError."""
    (tmp_path / "credentials.json").write_text(
        json.dumps({"api_key": "atomic-api-key", "inbox": "agno-agent@atomicmail.ai", "account_id": "account-1"})
    )
    client = mock_client_class.return_value.__aenter__.return_value
    client.post = AsyncMock(side_effect=[CHALLENGE_RESPONSE, SESSION_RESPONSE, CAPABILITY_RESPONSE])
    client.get = AsyncMock(return_value=_response(json_data={"apiUrl": "https://api.atomicmail.ai/jmap"}))
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = await tools.asend_email(to="someone@example.com", subject="Hi", body="Hello there")

    assert "error" in result
    assert "AtomicMail request failed" in result["error"]


@pytest.mark.asyncio
@patch("agno.tools.atomic_mail.httpx.AsyncClient")
async def test_alist_inbox_unexpected_jmap_body_returns_error(mock_client_class, tmp_path):
    """Async list parser also runs inside the try now: an unexpected 200 body returns
    an error dict rather than raising KeyError('methodResponses')."""
    (tmp_path / "credentials.json").write_text(
        json.dumps({"api_key": "atomic-api-key", "inbox": "agno-agent@atomicmail.ai", "account_id": "account-1"})
    )
    unexpected = _response(json_data={"unexpected": "shape"})
    client = mock_client_class.return_value.__aenter__.return_value
    client.post = AsyncMock(
        side_effect=[CHALLENGE_RESPONSE, SESSION_RESPONSE, CAPABILITY_RESPONSE, MAILBOX_QUERY_RESPONSE, unexpected]
    )
    client.get = AsyncMock(return_value=WELL_KNOWN_RESPONSE)
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = await tools.alist_inbox(limit=5)

    assert "error" in result
    assert "AtomicMail request failed" in result["error"]


# -- sent-mail filtering, auth reuse, parallel proof-of-work --------------------------

EMPTY_INBOX_RESPONSE = _response(
    json_data={"methodResponses": [["Email/query", {"ids": []}, "q0"], ["Email/get", {"list": []}, "g0"]]}
)
# A capability token with a known lifetime, so a test can move the clock past it.
SHORT_LIVED_CAPABILITY_JWT = _fake_jwt(
    {"inboxId": "agno-agent", "allowedFromDomain": "atomicmail.ai", "iat": 1_000_000, "exp": 1_000_120}
)
SHORT_LIVED_CAPABILITY_RESPONSE = _response(headers={"Authorization": f"Bearer {SHORT_LIVED_CAPABILITY_JWT}"})


def _write_credentials(tmp_path):
    (tmp_path / "credentials.json").write_text(
        json.dumps({"api_key": "atomic-api-key", "inbox": "agno-agent@atomicmail.ai", "account_id": "account-1"})
    )


def _posted_urls(client) -> list:
    return [call.args[0] for call in client.post.call_args_list]


@patch("agno.tools.atomic_mail.httpx.Client")
def test_list_inbox_query_excludes_drafts_on_the_wire(mock_client_class, tmp_path):
    """send_email files the outgoing message in the inbox mailbox with `$draft` set, so
    the inbox query must exclude that keyword or sent mail reads back as received."""
    _write_credentials(tmp_path)
    client = mock_client_class.return_value.__enter__.return_value
    client.post.side_effect = [
        CHALLENGE_RESPONSE,
        SESSION_RESPONSE,
        CAPABILITY_RESPONSE,
        MAILBOX_QUERY_RESPONSE,
        EMPTY_INBOX_RESPONSE,
    ]
    client.get.return_value = WELL_KNOWN_RESPONSE
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    tools.list_inbox(limit=5)

    jmap_body = client.post.call_args_list[-1].kwargs["json"]
    query = next(call for call in jmap_body["methodCalls"] if call[0] == "Email/query")
    get = next(call for call in jmap_body["methodCalls"] if call[0] == "Email/get")
    assert query[1]["filter"]["notKeyword"] == "$draft"
    assert query[1]["filter"]["inMailbox"] == "mailbox-inbox"
    assert "keywords" in get[1]["properties"]


@patch("agno.tools.atomic_mail.httpx.Client")
def test_list_inbox_drops_draft_messages_from_result(mock_client_class, tmp_path):
    """A message carrying `$draft` is our own outgoing mail, never a received one."""
    _write_credentials(tmp_path)
    received = {
        "id": "email-received",
        "from": [{"email": "someone@example.com"}],
        "to": [{"email": "agno-agent@atomicmail.ai"}],
        "subject": "Hi",
        "receivedAt": "2026-07-23T00:00:00Z",
        "preview": "Hello there",
        "keywords": {},
    }
    sent = {
        "id": "email-sent",
        "from": [{"email": "agno-agent@atomicmail.ai"}],
        "to": [{"email": "third-party@example.com"}],
        "subject": "Outgoing",
        "receivedAt": "2026-07-23T00:01:00Z",
        "preview": "Sent by us",
        "keywords": {"$draft": True},
    }
    inbox_response = _response(
        json_data={
            "methodResponses": [
                ["Email/query", {"ids": ["email-sent", "email-received"]}, "q0"],
                ["Email/get", {"list": [sent, received]}, "g0"],
            ]
        }
    )
    client = mock_client_class.return_value.__enter__.return_value
    client.post.side_effect = [
        CHALLENGE_RESPONSE,
        SESSION_RESPONSE,
        CAPABILITY_RESPONSE,
        MAILBOX_QUERY_RESPONSE,
        inbox_response,
    ]
    client.get.return_value = WELL_KNOWN_RESPONSE
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = tools.list_inbox(limit=5)

    assert result["count"] == 1
    assert [email["id"] for email in result["emails"]] == ["email-received"]


@patch("agno.tools.atomic_mail.httpx.Client")
def test_list_inbox_reuses_auth_within_token_window(mock_client_class, tmp_path):
    """The capability token lives 120s and the JMAP topology is stable per inbox, so a
    second call inside that window must issue only the JMAP request, no handshake."""
    _write_credentials(tmp_path)
    client = mock_client_class.return_value.__enter__.return_value
    client.post.side_effect = [
        CHALLENGE_RESPONSE,
        SESSION_RESPONSE,
        CAPABILITY_RESPONSE,
        MAILBOX_QUERY_RESPONSE,
        EMPTY_INBOX_RESPONSE,
        EMPTY_INBOX_RESPONSE,
    ]
    client.get.return_value = WELL_KNOWN_RESPONSE
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    first = tools.list_inbox(limit=5)
    second = tools.list_inbox(limit=5)

    assert first == second == {"inbox": "agno-agent@atomicmail.ai", "count": 0, "emails": []}
    urls = _posted_urls(client)
    assert urls.count("https://auth.atomicmail.ai/api/v1/challenge") == 1
    assert len(urls) == 6
    assert client.get.call_count == 1


@patch("agno.tools.atomic_mail.httpx.Client")
def test_list_inbox_reauthenticates_after_token_expiry(mock_client_class, tmp_path):
    _write_credentials(tmp_path)
    client = mock_client_class.return_value.__enter__.return_value
    client.post.side_effect = [
        CHALLENGE_RESPONSE,
        SESSION_RESPONSE,
        SHORT_LIVED_CAPABILITY_RESPONSE,
        MAILBOX_QUERY_RESPONSE,
        EMPTY_INBOX_RESPONSE,
        EMPTY_INBOX_RESPONSE,  # second call inside the window: no handshake
        CHALLENGE_RESPONSE,
        SESSION_RESPONSE,
        SHORT_LIVED_CAPABILITY_RESPONSE,
        MAILBOX_QUERY_RESPONSE,
        EMPTY_INBOX_RESPONSE,
    ]
    client.get.return_value = WELL_KNOWN_RESPONSE
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    with patch("agno.tools.atomic_mail.time.monotonic") as clock:
        clock.return_value = 1000.0
        tools.list_inbox(limit=5)
        clock.return_value = 1000.0 + 10.0
        tools.list_inbox(limit=5)
        assert _posted_urls(client).count("https://auth.atomicmail.ai/api/v1/challenge") == 1
        clock.return_value = 1000.0 + 200.0  # well past the 120s token lifetime
        result = tools.list_inbox(limit=5)

    assert result == {"inbox": "agno-agent@atomicmail.ai", "count": 0, "emails": []}
    assert _posted_urls(client).count("https://auth.atomicmail.ai/api/v1/challenge") == 2


@pytest.mark.asyncio
@patch("agno.tools.atomic_mail.httpx.AsyncClient")
async def test_alist_inbox_reuses_auth_within_token_window(mock_client_class, tmp_path):
    """The async twin is a hand-maintained duplicate; it must reuse the token too."""
    _write_credentials(tmp_path)
    client = mock_client_class.return_value.__aenter__.return_value
    client.post = AsyncMock(
        side_effect=[
            CHALLENGE_RESPONSE,
            SESSION_RESPONSE,
            CAPABILITY_RESPONSE,
            MAILBOX_QUERY_RESPONSE,
            EMPTY_INBOX_RESPONSE,
            EMPTY_INBOX_RESPONSE,
        ]
    )
    client.get = AsyncMock(return_value=WELL_KNOWN_RESPONSE)
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    first = await tools.alist_inbox(limit=5)
    second = await tools.alist_inbox(limit=5)

    assert first == second == {"inbox": "agno-agent@atomicmail.ai", "count": 0, "emails": []}
    urls = _posted_urls(client)
    assert urls.count("https://auth.atomicmail.ai/api/v1/challenge") == 1
    assert len(urls) == 6


def _sequential_pow(challenge: str, difficulty: int) -> dict:
    """The solve as shipped in #9130: nonces 0, 1, 2, ... on one thread."""
    from agno.tools.atomic_mail import POW_HASH_BYTES, POW_SCRYPT_N, POW_SCRYPT_P, POW_SCRYPT_R, POW_SCRYPT_SALT

    nonce = 0
    while True:
        digest = hashlib.scrypt(
            f"{challenge}:{nonce}".encode(),
            salt=POW_SCRYPT_SALT.encode(),
            n=POW_SCRYPT_N,
            r=POW_SCRYPT_R,
            p=POW_SCRYPT_P,
            dklen=POW_HASH_BYTES,
        )
        if AtomicMailTools._has_leading_zero_bits(digest, difficulty):
            return {"powHex": digest.hex(), "nonce": str(nonce)}
        nonce += 1


def test_solve_pow_single_worker_matches_sequential_search():
    assert AtomicMailTools._solve_pow("challenge-123", 4, None, workers=1) == _sequential_pow("challenge-123", 4)


def test_solve_pow_parallel_returns_a_valid_proof():
    """The server recomputes scrypt(challenge:nonce) and checks the leading bits, so the
    nonce/digest pair returned by the pool must be genuine, not just well-formed."""
    from agno.tools.atomic_mail import POW_HASH_BYTES, POW_SCRYPT_N, POW_SCRYPT_P, POW_SCRYPT_R, POW_SCRYPT_SALT

    solved = AtomicMailTools._solve_pow("challenge-123", 4, None, workers=4)

    digest = hashlib.scrypt(
        f"challenge-123:{solved['nonce']}".encode(),
        salt=POW_SCRYPT_SALT.encode(),
        n=POW_SCRYPT_N,
        r=POW_SCRYPT_R,
        p=POW_SCRYPT_P,
        dklen=POW_HASH_BYTES,
    )
    assert digest.hex() == solved["powHex"]
    assert AtomicMailTools._has_leading_zero_bits(digest, 4)


def test_solve_pow_parallel_is_bounded_by_pow_timeout():
    with pytest.raises(ValueError, match="did not converge"):
        AtomicMailTools._solve_pow("challenge", difficulty=255, max_seconds=0.0, workers=4)


def test_pow_workers_defaults_bounded_and_reaches_the_solve(tmp_path):
    """Default stays well under cpu_count so the solve cannot starve the host; the
    configured value is what the handshake actually hands to `_solve_pow`."""
    import os

    assert AtomicMailTools(credentials_dir=str(tmp_path)).pow_workers == min(4, os.cpu_count() or 1)

    tools = AtomicMailTools(credentials_dir=str(tmp_path), pow_workers=1)
    assert tools.pow_workers == 1
    with patch("agno.tools.atomic_mail.httpx.Client") as mock_client_class:
        client = mock_client_class.return_value.__enter__.return_value
        client.post.side_effect = [CHALLENGE_RESPONSE, SESSION_RESPONSE, CAPABILITY_RESPONSE]
        client.get.return_value = WELL_KNOWN_RESPONSE
        with patch.object(AtomicMailTools, "_solve_pow", wraps=AtomicMailTools._solve_pow) as solve_spy:
            tools.register_inbox("agno-agent")

    assert solve_spy.call_args.args[-1] == 1 or solve_spy.call_args.kwargs.get("workers") == 1


@patch("agno.tools.atomic_mail.httpx.Client")
def test_forced_register_drops_cached_auth_of_replaced_inbox(mock_client_class, tmp_path):
    """After `forced=True` swaps the credentials, the next call must authenticate the new
    inbox rather than keep sending to the old one's cached token."""
    _write_credentials(tmp_path)
    new_capability = _fake_jwt({"inboxId": "new-agent", "allowedFromDomain": "atomicmail.ai", "exp": 9999999999})
    new_capability_response = _response(headers={"Authorization": f"Bearer {new_capability}"})
    new_session_response = _response(
        headers={"Authorization": f"Bearer {SESSION_JWT}"},
        json_data={"apiKey": "new-api-key"},
        text='{"apiKey": "new-api-key"}',
    )
    client = mock_client_class.return_value.__enter__.return_value
    client.post.side_effect = [
        CHALLENGE_RESPONSE,
        SESSION_RESPONSE,
        CAPABILITY_RESPONSE,
        MAILBOX_QUERY_RESPONSE,
        EMPTY_INBOX_RESPONSE,
        EMPTY_INBOX_RESPONSE,  # second call: served from the cache
        # register_inbox(forced=True) for a different inbox
        CHALLENGE_RESPONSE,
        new_session_response,
        new_capability_response,
        # list_inbox must authenticate again, with the new key
        CHALLENGE_RESPONSE,
        new_session_response,
        new_capability_response,
        MAILBOX_QUERY_RESPONSE,
        EMPTY_INBOX_RESPONSE,
    ]
    client.get.return_value = WELL_KNOWN_RESPONSE
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    tools.list_inbox(limit=5)
    tools.list_inbox(limit=5)
    assert _posted_urls(client).count("https://auth.atomicmail.ai/api/v1/challenge") == 1
    assert tools.register_inbox("new-agent", forced=True)["inbox"] == "new-agent@atomicmail.ai"
    result = tools.list_inbox(limit=5)

    assert result["inbox"] == "new-agent@atomicmail.ai"
    session_payloads = [
        call.kwargs["json"]
        for call in client.post.call_args_list
        if call.args[0] == "https://auth.atomicmail.ai/api/v1/session"
    ]
    assert [payload.get("apiKey") for payload in session_payloads] == ["atomic-api-key", None, "new-api-key"]


@patch("agno.tools.atomic_mail.httpx.Client")
def test_capability_token_without_numeric_exp_is_not_cached(mock_client_class, tmp_path):
    """`exp`/`iat` are server-supplied; a null or missing `exp` must mean "do not reuse",
    never a TypeError escaping the tool."""
    _write_credentials(tmp_path)
    no_exp = _fake_jwt({"inboxId": "agno-agent", "allowedFromDomain": "atomicmail.ai", "exp": None})
    no_exp_response = _response(headers={"Authorization": f"Bearer {no_exp}"})
    client = mock_client_class.return_value.__enter__.return_value
    client.post.side_effect = [
        CHALLENGE_RESPONSE,
        SESSION_RESPONSE,
        no_exp_response,
        MAILBOX_QUERY_RESPONSE,
        EMPTY_INBOX_RESPONSE,
        CHALLENGE_RESPONSE,
        SESSION_RESPONSE,
        no_exp_response,
        MAILBOX_QUERY_RESPONSE,
        EMPTY_INBOX_RESPONSE,
    ]
    client.get.return_value = WELL_KNOWN_RESPONSE
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    first = tools.list_inbox(limit=5)
    second = tools.list_inbox(limit=5)

    assert first == second == {"inbox": "agno-agent@atomicmail.ai", "count": 0, "emails": []}
    assert _posted_urls(client).count("https://auth.atomicmail.ai/api/v1/challenge") == 2


@patch("agno.tools.atomic_mail.httpx.Client")
def test_list_inbox_reports_rejected_query_as_error(mock_client_class, tmp_path):
    """A server that rejects the query (e.g. `unsupportedFilter`) answers with method-level
    errors and no Email/get list. That must surface as an error, not as an empty inbox."""
    _write_credentials(tmp_path)
    rejected = _response(
        json_data={
            "methodResponses": [
                ["error", {"type": "unsupportedFilter"}, "q0"],
                ["error", {"type": "invalidResultReference"}, "g0"],
            ]
        }
    )
    client = mock_client_class.return_value.__enter__.return_value
    client.post.side_effect = [
        CHALLENGE_RESPONSE,
        SESSION_RESPONSE,
        CAPABILITY_RESPONSE,
        MAILBOX_QUERY_RESPONSE,
        rejected,
    ]
    client.get.return_value = WELL_KNOWN_RESPONSE
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    result = tools.list_inbox(limit=5)

    assert "error" in result
    assert "count" not in result


@patch("agno.tools.atomic_mail.httpx.Client")
def test_cached_auth_is_dropped_when_credentials_change_on_disk(mock_client_class, tmp_path):
    """Another instance or process can replace credentials.json (forced re-registration).
    A cached context belongs to the key it was minted from; a call after the swap must
    authenticate the new key, exactly as every call did before the cache existed."""
    _write_credentials(tmp_path)
    new_capability = _fake_jwt({"inboxId": "new-agent", "allowedFromDomain": "atomicmail.ai", "exp": 9999999999})
    client = mock_client_class.return_value.__enter__.return_value
    client.post.side_effect = [
        CHALLENGE_RESPONSE,
        SESSION_RESPONSE,
        CAPABILITY_RESPONSE,
        MAILBOX_QUERY_RESPONSE,
        EMPTY_INBOX_RESPONSE,
        EMPTY_INBOX_RESPONSE,  # second call: served from the cache
        CHALLENGE_RESPONSE,
        SESSION_RESPONSE,
        _response(headers={"Authorization": f"Bearer {new_capability}"}),
        MAILBOX_QUERY_RESPONSE,
        EMPTY_INBOX_RESPONSE,
    ]
    client.get.return_value = WELL_KNOWN_RESPONSE
    tools = AtomicMailTools(credentials_dir=str(tmp_path))

    tools.list_inbox(limit=5)
    tools.list_inbox(limit=5)
    assert _posted_urls(client).count("https://auth.atomicmail.ai/api/v1/challenge") == 1
    (tmp_path / "credentials.json").write_text(
        json.dumps({"api_key": "new-api-key", "inbox": "new-agent@atomicmail.ai", "account_id": "account-2"})
    )
    result = tools.list_inbox(limit=5)

    assert result["inbox"] == "new-agent@atomicmail.ai"
    session_payloads = [
        call.kwargs["json"]
        for call in client.post.call_args_list
        if call.args[0] == "https://auth.atomicmail.ai/api/v1/session"
    ]
    assert [payload["apiKey"] for payload in session_payloads] == ["atomic-api-key", "new-api-key"]


def test_solve_pow_prefers_a_solution_over_a_concurrent_timeout():
    """One worker can cross the deadline while another is mid-way through the winning
    hash. The proof it returns is valid and must win over the timeout."""
    import threading

    worker_1_hashing = threading.Event()
    release_worker_1 = threading.Event()
    clock_calls = 0

    def clock():
        nonlocal clock_calls
        clock_calls += 1
        return 0.0 if clock_calls == 1 else 2.0  # deadline computed at 0, every later check is past it

    def scrypt(data, **kwargs):
        nonce = int(data.decode().rsplit(":", 1)[1])
        if nonce == 0:
            # worker 0: no proof, and it trips the deadline only once worker 1 is mid-hash
            worker_1_hashing.wait(1)
            threading.Timer(0.05, release_worker_1.set).start()
            return b"\xff"
        worker_1_hashing.set()
        release_worker_1.wait(1)
        return b"\x00"  # worker 1: a valid proof, finished after worker 0 timed out

    with patch("agno.tools.atomic_mail.time.monotonic", side_effect=clock):
        with patch("agno.tools.atomic_mail.hashlib.scrypt", side_effect=scrypt):
            solved = AtomicMailTools._solve_pow("challenge", difficulty=1, max_seconds=1.0, workers=2)

    assert solved == {"powHex": "00", "nonce": "1"}
