import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agno.tools.sendhq import MAX_BODY_CHARS, SendHQTools

TOOL_NAMES = {"send_email", "reply_to_email", "list_emails", "get_email", "get_thread"}

RECEIVED = {
    "id": "em_in1",
    "threadId": "em_out0",
    "direction": "in",
    "status": "received",
    "from": "Ada <ada@customer.test>",
    "to": ["support@acme.test"],
    "cc": [],
    "replyTo": None,
    "subject": "Order 42 is late",
    "text": "Hi, where is my order?",
    "html": "<p>Hi, where is my order?</p>",
    "raw": "MIME...",
    "unread": True,
    "category": "primary",
    "attachmentCount": 1,
    "attachments": [{"id": "att_1", "filename": "receipt.pdf", "sizeBytes": 1200}],
    "createdAt": "2026-10-06T10:00:00.000Z",
    # Every email carries its own delivery `error` (null unless it failed).
    "error": None,
}
SENT = {
    **RECEIVED,
    "id": "em_out0",
    "direction": "out",
    "from": "support@acme.test",
    "to": ["ada@customer.test"],
    "subject": "Your order",
}


def _response(status=200, payload=None):
    return httpx.Response(
        status, json=payload if payload is not None else {}, request=httpx.Request("GET", "https://x")
    )


@pytest.fixture
def tools():
    return SendHQTools(api_key="re_test", from_email="Acme <support@acme.test>")


def test_registers_sync_and_async_tools(tools):
    assert tools.name == "sendhq_tools"
    assert set(tools.functions) == TOOL_NAMES
    assert set(tools.async_functions) == TOOL_NAMES


def test_disabled_tool_is_not_registered():
    tools = SendHQTools(api_key="re_test", enable_reply_to_email=False)

    assert "reply_to_email" not in tools.functions
    assert "reply_to_email" not in tools.async_functions
    assert "send_email" in tools.functions


def test_all_overrides_disabled_flags():
    tools = SendHQTools(api_key="re_test", enable_send_email=False, enable_get_thread=False, all=True)

    assert set(tools.functions) == TOOL_NAMES


def test_reads_configuration_from_environment():
    env = {
        "SENDHQ_API_KEY": "re_env",
        "SENDHQ_FROM_EMAIL": "bot@acme.test",
        "SENDHQ_BASE_URL": "https://eu.example/api/v1/",
    }
    with patch.dict("os.environ", env):
        tools = SendHQTools()

    assert tools.api_key == "re_env"
    assert tools.from_email == "bot@acme.test"
    assert tools.base_url == "https://eu.example/api/v1"


def test_missing_api_key_returns_error_without_request():
    with patch.dict("os.environ", {}, clear=True), patch("agno.tools.sendhq.httpx.request") as request:
        tools = SendHQTools(from_email="bot@acme.test")
        result = json.loads(tools.send_email(to=["a@b.test"], subject="Hi", body="Hello"))

    assert "SENDHQ_API_KEY" in result["error"]
    request.assert_not_called()


def test_send_email_posts_payload_and_idempotency_key(tools):
    with patch(
        "agno.tools.sendhq.httpx.request", return_value=_response(201, {"id": "em_1", "threadId": "em_1"})
    ) as request:
        result = json.loads(
            tools.send_email(
                to=["ada@customer.test"],
                subject="Welcome",
                body="Hello Ada",
                cc=["ops@acme.test"],
                reply_to="help@acme.test",
                idempotency_key="welcome-ada",
            )
        )

    assert result == {"id": "em_1", "thread_id": "em_1", "to": ["ada@customer.test"]}
    method, url = request.call_args.args
    kwargs = request.call_args.kwargs
    assert (method, url) == ("POST", "https://sendhq.cc/api/v1/emails")
    assert kwargs["json"] == {
        "from": "Acme <support@acme.test>",
        "to": ["ada@customer.test"],
        "subject": "Welcome",
        "text": "Hello Ada",
        "cc": ["ops@acme.test"],
        "reply_to": "help@acme.test",
    }
    assert kwargs["headers"]["Authorization"] == "Bearer re_test"
    assert kwargs["headers"]["Idempotency-Key"] == "welcome-ada"


def test_send_email_without_sender_fails_before_request():
    with patch.dict("os.environ", {}, clear=True), patch("agno.tools.sendhq.httpx.request") as request:
        tools = SendHQTools(api_key="re_test")
        result = json.loads(tools.send_email(to=["a@b.test"], subject="Hi", body="Hello"))

    assert "SENDHQ_FROM_EMAIL" in result["error"]
    request.assert_not_called()


def test_api_error_returns_message_and_status(tools):
    error = {"error": {"message": "The sender domain is not owned by this workspace", "status": 403}}
    with patch("agno.tools.sendhq.httpx.request", return_value=_response(403, error)):
        result = json.loads(tools.send_email(to=["a@b.test"], subject="Hi", body="Hello"))

    assert result == {"error": "The sender domain is not owned by this workspace", "status": 403}


def test_api_error_keeps_code_explanation_and_remedy(tools):
    error = {
        "error": {
            "message": "Domain not verified",
            "status": 422,
            "code": "domain_unverified",
            "explanation": "acme.test is pending",
            "remedy": "Publish the DNS records",
        }
    }
    with patch("agno.tools.sendhq.httpx.request", return_value=_response(422, error)):
        result = json.loads(tools.send_email(to=["a@b.test"], subject="Hi", body="Hello"))

    assert result == {
        "error": "Domain not verified",
        "status": 422,
        "code": "domain_unverified",
        "explanation": "acme.test is pending",
        "remedy": "Publish the DNS records",
    }


def test_non_json_error_body(tools):
    response = httpx.Response(502, text="Bad gateway", request=httpx.Request("GET", "https://x"))
    with patch("agno.tools.sendhq.httpx.request", return_value=response):
        result = json.loads(tools.list_emails())

    assert result == {"error": "Bad gateway", "status": 502}


def test_network_error_is_returned(tools):
    with patch("agno.tools.sendhq.httpx.request", side_effect=httpx.ConnectError("boom")):
        result = json.loads(tools.list_emails())

    assert result == {"error": "boom"}


def test_reply_to_received_email_answers_sender_from_receiving_inbox():
    tools = SendHQTools(api_key="re_test")
    responses = [_response(200, RECEIVED), _response(201, {"id": "em_r1", "threadId": "em_out0"})]
    with patch("agno.tools.sendhq.httpx.request", side_effect=responses) as request:
        result = json.loads(tools.reply_to_email(email_id="em_in1", body="It ships today."))

    assert result == {"id": "em_r1", "thread_id": "em_out0", "to": ["Ada <ada@customer.test>"]}
    assert request.call_args_list[0].args == ("GET", "https://sendhq.cc/api/v1/emails/em_in1")
    payload = request.call_args_list[1].kwargs["json"]
    assert payload == {
        "from": "support@acme.test",
        "to": ["Ada <ada@customer.test>"],
        "subject": "Re: Order 42 is late",
        "text": "It ships today.",
        "reply_to_email_id": "em_in1",
    }


def test_reply_prefers_reply_to_header_and_keeps_existing_re_prefix(tools):
    parent = {**RECEIVED, "replyTo": "tickets@customer.test", "subject": "RE: Order 42"}
    responses = [_response(200, parent), _response(201, {"id": "em_r2", "threadId": "em_out0"})]
    with patch("agno.tools.sendhq.httpx.request", side_effect=responses) as request:
        tools.reply_to_email(email_id="em_in1", body="Done.")

    payload = request.call_args_list[1].kwargs["json"]
    assert payload["to"] == ["tickets@customer.test"]
    assert payload["subject"] == "RE: Order 42"
    # A configured sender wins over the receiving inbox address.
    assert payload["from"] == "Acme <support@acme.test>"


def test_follow_up_to_sent_email_goes_to_original_recipients():
    tools = SendHQTools(api_key="re_test")
    responses = [_response(200, SENT), _response(201, {"id": "em_f1", "threadId": "em_out0"})]
    with patch("agno.tools.sendhq.httpx.request", side_effect=responses) as request:
        tools.reply_to_email(email_id="em_out0", body="Just checking in.")

    payload = request.call_args_list[1].kwargs["json"]
    assert payload["from"] == "support@acme.test"
    assert payload["to"] == ["ada@customer.test"]
    assert payload["subject"] == "Re: Your order"


def test_reply_to_missing_email_returns_api_error(tools):
    with patch(
        "agno.tools.sendhq.httpx.request",
        return_value=_response(404, {"error": {"message": "Email not found", "status": 404}}),
    ) as request:
        result = json.loads(tools.reply_to_email(email_id="em_nope", body="Hi"))

    assert result == {"error": "Email not found", "status": 404}
    assert request.call_count == 1


def test_list_emails_sends_filters_and_returns_summaries(tools):
    with patch(
        "agno.tools.sendhq.httpx.request", return_value=_response(200, {"data": [RECEIVED], "count": 1})
    ) as request:
        result = json.loads(tools.list_emails(unread=True, query="order", limit=500))

    assert request.call_args.kwargs["params"] == {"limit": 100, "direction": "in", "unread": "true", "query": "order"}
    assert result["count"] == 1
    email = result["emails"][0]
    assert email["id"] == "em_in1"
    assert email["thread_id"] == "em_out0"
    assert email["snippet"] == "Hi, where is my order?"
    assert "raw" not in email and "html" not in email


def test_list_emails_both_directions_omits_direction(tools):
    with patch("agno.tools.sendhq.httpx.request", return_value=_response(200, {"data": []})) as request:
        tools.list_emails(direction=None)

    assert "direction" not in request.call_args.kwargs["params"]


def test_get_email_returns_body_and_attachments(tools):
    with patch("agno.tools.sendhq.httpx.request", return_value=_response(200, RECEIVED)):
        result = json.loads(tools.get_email(email_id="em_in1"))

    assert result["body"] == "Hi, where is my order?"
    assert result["attachments"] == [{"id": "att_1", "filename": "receipt.pdf", "size_bytes": 1200}]
    assert "raw" not in result


def test_email_error_field_is_not_a_request_error(tools):
    with patch("agno.tools.sendhq.httpx.request", return_value=_response(200, RECEIVED)):
        result = json.loads(tools.get_email(email_id="em_in1"))

    assert "error" not in result
    assert "delivery_error" not in result
    assert result["id"] == "em_in1"


def test_failed_email_reports_delivery_error(tools):
    failed = {**SENT, "status": "failed", "error": "Recipient count exceeds 50."}
    with patch("agno.tools.sendhq.httpx.request", return_value=_response(200, {"data": [failed]})):
        result = json.loads(tools.list_emails(direction="out"))

    assert result["emails"][0]["status"] == "failed"
    assert result["emails"][0]["delivery_error"] == "Recipient count exceeds 50."


def test_get_email_truncates_long_bodies(tools):
    long_email = {**RECEIVED, "text": "x" * (MAX_BODY_CHARS + 10)}
    with patch("agno.tools.sendhq.httpx.request", return_value=_response(200, long_email)):
        result = json.loads(tools.get_email(email_id="em_in1"))

    assert len(result["body"]) == MAX_BODY_CHARS
    assert result["body_truncated"] is True


def test_get_email_falls_back_to_html_body(tools):
    with patch("agno.tools.sendhq.httpx.request", return_value=_response(200, {**RECEIVED, "text": None})):
        result = json.loads(tools.get_email(email_id="em_in1"))

    assert result["body"] == "<p>Hi, where is my order?</p>"


def test_get_thread_returns_messages_in_order(tools):
    thread = {"id": "em_out0", "subject": "Your order", "data": [SENT, RECEIVED]}
    with patch("agno.tools.sendhq.httpx.request", return_value=_response(200, thread)) as request:
        result = json.loads(tools.get_thread(thread_id="em_out0"))

    assert request.call_args.args == ("GET", "https://sendhq.cc/api/v1/threads/em_out0")
    assert result["thread_id"] == "em_out0"
    assert [m["id"] for m in result["messages"]] == ["em_out0", "em_in1"]


def test_empty_ids_are_rejected_without_request(tools):
    with patch("agno.tools.sendhq.httpx.request") as request:
        assert "error" in json.loads(tools.get_email(email_id=""))
        assert "error" in json.loads(tools.get_thread(thread_id=""))
        assert "error" in json.loads(tools.reply_to_email(email_id="", body="Hi"))

    request.assert_not_called()


def _async_client(*responses):
    client = MagicMock()
    client.request = AsyncMock(side_effect=list(responses))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def test_async_send_email(tools):
    client = _async_client(_response(201, {"id": "em_a1", "threadId": "em_a1"}))
    with patch("agno.tools.sendhq.httpx.AsyncClient", return_value=client):
        result = json.loads(asyncio.run(tools.asend_email(to=["ada@customer.test"], subject="Hi", body="Hello")))

    assert result["id"] == "em_a1"
    assert client.request.call_args.args == ("POST", "https://sendhq.cc/api/v1/emails")


def test_async_reply_to_email():
    tools = SendHQTools(api_key="re_test")
    client = _async_client(_response(200, RECEIVED), _response(201, {"id": "em_ar", "threadId": "em_out0"}))
    with patch("agno.tools.sendhq.httpx.AsyncClient", return_value=client):
        result = json.loads(asyncio.run(tools.areply_to_email(email_id="em_in1", body="On its way.")))

    assert result["to"] == ["Ada <ada@customer.test>"]
    assert client.request.call_args_list[1].kwargs["json"]["reply_to_email_id"] == "em_in1"


def test_async_list_get_and_thread(tools):
    client = _async_client(
        _response(200, {"data": [RECEIVED]}),
        _response(200, RECEIVED),
        _response(200, {"id": "em_out0", "subject": "Your order", "data": [SENT]}),
    )
    with patch("agno.tools.sendhq.httpx.AsyncClient", return_value=client):
        listed = json.loads(asyncio.run(tools.alist_emails()))
        email = json.loads(asyncio.run(tools.aget_email(email_id="em_in1")))
        thread = json.loads(asyncio.run(tools.aget_thread(thread_id="em_out0")))

    assert listed["emails"][0]["id"] == "em_in1"
    assert email["body"] == "Hi, where is my order?"
    assert thread["messages"][0]["id"] == "em_out0"
