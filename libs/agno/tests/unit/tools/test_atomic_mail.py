import base64
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
