import asyncio
import base64
import contextlib
import hashlib
import json
import secrets
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from agno.os.interfaces.lark.helpers import LarkClient

VERIF_TOKEN = "test-verif-token"
ENCRYPT_KEY = "test-encrypt-key"


# === Helpers ===


def _make_agent_mock(db=None):
    agent = AsyncMock()
    agent.name = "test_agent"
    agent.id = "test_agent"
    agent.db = db
    agent.arun = AsyncMock(
        return_value=Mock(
            status="OK",
            content="agent reply",
            reasoning_content=None,
            images=None,
            files=None,
            videos=None,
            audio=None,
            response_audio=None,
            tools=None,
        )
    )
    return agent


def _build_app(agent_mock, streaming=False, encrypt_key=None, verification_token=VERIF_TOKEN, **kwargs):
    from agno.os.interfaces.lark.router import attach_routes

    app = FastAPI()
    router = APIRouter()
    attach_routes(
        router,
        agent=agent_mock,
        app_id="cli_test",
        app_secret="secret",
        verification_token=verification_token,
        encrypt_key=encrypt_key,
        streaming=streaming,
        **kwargs,
    )
    app.include_router(router)
    return app


def _make_lark_event(
    text="hello",
    chat_type="p2p",
    chat_id="oc_test",
    sender_open_id="ou_sender",
    message_id="om_test",
    mentions=None,
):
    event = {
        "schema": "2.0",
        "header": {
            "event_id": "evt_" + secrets.token_hex(4),
            "event_type": "im.message.receive_v1",
            "create_time": str(int(time.time() * 1000)),
            "token": VERIF_TOKEN,
            "app_id": "cli_test",
            "tenant_key": "test",
        },
        "event": {
            "sender": {"sender_id": {"open_id": sender_open_id, "user_id": "u1"}, "sender_type": "user"},
            "message": {
                "message_id": message_id,
                "chat_id": chat_id,
                "chat_type": chat_type,
                "message_type": "text",
                "content": json.dumps({"text": text}),
            },
        },
    }
    if mentions is not None:
        event["event"]["message"]["mentions"] = mentions
    return event


def _encrypt_payload(encrypt_key, plaintext_dict):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7

    key = hashlib.sha256(encrypt_key.encode()).digest()
    iv = b"0123456789abcdef"
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    padder = PKCS7(128).padder()
    padded = padder.update(json.dumps(plaintext_dict).encode()) + padder.finalize()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return {"encrypt": base64.b64encode(iv + ciphertext).decode()}


def _sign_body(encrypt_key, body_bytes, timestamp, nonce):
    sig_str = (timestamp + nonce + encrypt_key).encode("utf-8") + body_bytes
    return hashlib.sha256(sig_str).hexdigest()


@contextlib.contextmanager
def _mock_lark_client():
    """Mock all LarkClient async methods so tests never hit the real Lark API."""
    with contextlib.ExitStack() as stack:
        mocks = {
            "send_message": stack.enter_context(patch.object(LarkClient, "send_message", new_callable=AsyncMock)),
            "reply_message": stack.enter_context(
                patch.object(LarkClient, "reply_message", new_callable=AsyncMock, return_value="om_reply")
            ),
            "patch_card": stack.enter_context(patch.object(LarkClient, "patch_card", new_callable=AsyncMock)),
            "get_bot_open_id": stack.enter_context(
                patch.object(LarkClient, "get_bot_open_id", new_callable=AsyncMock, return_value="ou_bot")
            ),
            "download_resource": stack.enter_context(
                patch.object(LarkClient, "download_resource", new_callable=AsyncMock, return_value=None)
            ),
            "upload_image": stack.enter_context(
                patch.object(LarkClient, "upload_image", new_callable=AsyncMock, return_value="img_key")
            ),
            "upload_file": stack.enter_context(
                patch.object(LarkClient, "upload_file", new_callable=AsyncMock, return_value="file_key")
            ),
        }
        yield mocks


async def _wait_for_agent_call(agent_mock, timeout=5.0):
    elapsed = 0.0
    while not agent_mock.arun.called and elapsed < timeout:
        await asyncio.sleep(0.1)
        elapsed += 0.1


async def _wait_for_mock_call(mock_obj, timeout=5.0):
    elapsed = 0.0
    while not mock_obj.called and elapsed < timeout:
        await asyncio.sleep(0.1)
        elapsed += 0.1
    await asyncio.sleep(0)


# === URL Verification Challenge ===


def test_url_verification_challenge_plaintext():
    agent = _make_agent_mock()
    with _mock_lark_client():
        app = _build_app(agent)
        client = TestClient(app)
        resp = client.post("/webhook", json={"type": "url_verification", "challenge": "abc123", "token": VERIF_TOKEN})
        assert resp.status_code == 200
        assert resp.json() == {"challenge": "abc123"}


def test_url_verification_challenge_encrypted():
    agent = _make_agent_mock()
    challenge_body = {"type": "url_verification", "challenge": "enc_456", "token": VERIF_TOKEN}
    encrypted = _encrypt_payload(ENCRYPT_KEY, challenge_body)
    with _mock_lark_client():
        app = _build_app(agent, encrypt_key=ENCRYPT_KEY)
        client = TestClient(app)
        resp = client.post("/webhook", json=encrypted)
        assert resp.status_code == 200
        assert resp.json() == {"challenge": "enc_456"}


def test_challenge_not_blocked_by_signature():
    """Challenge must be handled before signature verification (Lark may not sign it)."""
    agent = _make_agent_mock()
    challenge_body = {"type": "url_verification", "challenge": "no_sig", "token": VERIF_TOKEN}
    encrypted = _encrypt_payload(ENCRYPT_KEY, challenge_body)
    with _mock_lark_client():
        app = _build_app(agent, encrypt_key=ENCRYPT_KEY)
        client = TestClient(app)
        # POST without any X-Lark-Signature header — challenge should still succeed
        resp = client.post("/webhook", json=encrypted)
        assert resp.status_code == 200
        assert resp.json() == {"challenge": "no_sig"}


# === Signature Verification ===


def test_webhook_invalid_signature_403():
    agent = _make_agent_mock()
    event = _make_lark_event()
    encrypted = _encrypt_payload(ENCRYPT_KEY, event)
    with _mock_lark_client():
        app = _build_app(agent, encrypt_key=ENCRYPT_KEY)
        client = TestClient(app)
        resp = client.post(
            "/webhook",
            json=encrypted,
            headers={
                "X-Lark-Request-Timestamp": str(int(time.time())),
                "X-Lark-Request-Nonce": "nonce",
                "X-Lark-Signature": "invalid_signature",
            },
        )
        assert resp.status_code == 403


def test_webhook_valid_signature_accepted():
    agent = _make_agent_mock()
    event = _make_lark_event()
    encrypted = _encrypt_payload(ENCRYPT_KEY, event)
    body_bytes = json.dumps(encrypted).encode()
    timestamp = str(int(time.time()))
    nonce = "nonce123"
    signature = _sign_body(ENCRYPT_KEY, body_bytes, timestamp, nonce)
    with _mock_lark_client():
        app = _build_app(agent, encrypt_key=ENCRYPT_KEY, streaming=False)
        client = TestClient(app)
        resp = client.post(
            "/webhook",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Lark-Request-Timestamp": timestamp,
                "X-Lark-Request-Nonce": nonce,
                "X-Lark-Signature": signature,
            },
        )
        assert resp.status_code == 200


# === Verification Token ===


def test_invalid_verification_token_403():
    agent = _make_agent_mock()
    event = _make_lark_event()
    event["header"]["token"] = "wrong-token"
    with _mock_lark_client():
        app = _build_app(agent)
        client = TestClient(app)
        resp = client.post("/webhook", json=event)
        assert resp.status_code == 403


# === Message Processing ===


@pytest.mark.asyncio
async def test_text_message_p2p():
    agent = _make_agent_mock()
    with _mock_lark_client():
        app = _build_app(agent, streaming=False)
        client = TestClient(app)
        event = _make_lark_event(text="hello world", chat_type="p2p")
        resp = client.post("/webhook", json=event)
        assert resp.status_code == 200

        await _wait_for_agent_call(agent)
        agent.arun.assert_called_once()
        call_args = agent.arun.call_args
        assert call_args[0][0] == "hello world"
        assert call_args.kwargs["user_id"] == "ou_sender"
        assert call_args.kwargs["session_id"] == "lark:test_agent:oc_test"


@pytest.mark.asyncio
async def test_group_mention_processed():
    agent = _make_agent_mock()
    mentions = [{"key": "@_user_1", "id": {"open_id": "ou_bot"}, "name": "bot"}]
    with _mock_lark_client():
        app = _build_app(agent, streaming=False)
        client = TestClient(app)
        event = _make_lark_event(text="@_user_1 hello", chat_type="group", mentions=mentions)
        resp = client.post("/webhook", json=event)
        assert resp.status_code == 200

        await _wait_for_agent_call(agent)
        agent.arun.assert_called_once()
        # Mention placeholder stripped before sending to agent
        assert call_args_text(agent) == "hello"


@pytest.mark.asyncio
async def test_group_no_mention_skipped():
    agent = _make_agent_mock()
    with _mock_lark_client():
        app = _build_app(agent, streaming=False)
        client = TestClient(app)
        event = _make_lark_event(text="hello everyone", chat_type="group")
        resp = client.post("/webhook", json=event)
        assert resp.status_code == 200

        await asyncio.sleep(1.0)
        agent.arun.assert_not_called()


@pytest.mark.asyncio
async def test_dm_always_processed():
    agent = _make_agent_mock()
    with _mock_lark_client():
        app = _build_app(agent, streaming=False, reply_to_mentions_only=True)
        client = TestClient(app)
        event = _make_lark_event(text="hi", chat_type="p2p")
        resp = client.post("/webhook", json=event)
        assert resp.status_code == 200

        await _wait_for_agent_call(agent)
        agent.arun.assert_called_once()


@pytest.mark.asyncio
async def test_group_no_mention_processed_when_flag_false():
    agent = _make_agent_mock()
    with _mock_lark_client():
        app = _build_app(agent, streaming=False, reply_to_mentions_only=False)
        client = TestClient(app)
        event = _make_lark_event(text="hello", chat_type="group")
        resp = client.post("/webhook", json=event)
        assert resp.status_code == 200

        await _wait_for_agent_call(agent)
        agent.arun.assert_called_once()


# === Commands ===


@pytest.mark.asyncio
async def test_new_command_resets_session():
    from agno.db.base import BaseDb

    db = Mock(spec=BaseDb)
    db.upsert_session = Mock()
    agent = _make_agent_mock(db=db)
    with _mock_lark_client() as mocks:
        app = _build_app(agent, streaming=False)
        client = TestClient(app)
        event = _make_lark_event(text="/new", chat_type="p2p")
        resp = client.post("/webhook", json=event)
        assert resp.status_code == 200

        await _wait_for_mock_call(mocks["send_message"])
        agent.arun.assert_not_called()
        db.upsert_session.assert_called_once()
        mocks["send_message"].assert_called()


@pytest.mark.asyncio
async def test_help_command():
    agent = _make_agent_mock()
    with _mock_lark_client() as mocks:
        app = _build_app(agent, streaming=False)
        client = TestClient(app)
        event = _make_lark_event(text="/help", chat_type="p2p")
        resp = client.post("/webhook", json=event)
        assert resp.status_code == 200

        await _wait_for_mock_call(mocks["send_message"])
        agent.arun.assert_not_called()
        mocks["send_message"].assert_called_once()


# === Error Handling ===


@pytest.mark.asyncio
async def test_agent_error_sends_error_message():
    agent = _make_agent_mock()
    agent.arun = AsyncMock(
        return_value=Mock(
            status="ERROR",
            content="internal error",
            reasoning_content=None,
            images=None,
            files=None,
            videos=None,
            audio=None,
            response_audio=None,
            tools=None,
        )
    )
    with _mock_lark_client() as mocks:
        app = _build_app(agent, streaming=False)
        client = TestClient(app)
        event = _make_lark_event(text="trigger error", chat_type="p2p")
        resp = client.post("/webhook", json=event)
        assert resp.status_code == 200

        await _wait_for_mock_call(mocks["reply_message"])
        # An error card should be sent (via reply or send)
        assert mocks["reply_message"].called or mocks["send_message"].called


@pytest.mark.asyncio
async def test_agent_exception_sends_fallback():
    agent = _make_agent_mock()
    agent.arun = AsyncMock(side_effect=RuntimeError("agent crashed"))
    with _mock_lark_client() as mocks:
        app = _build_app(agent, streaming=False)
        client = TestClient(app)
        event = _make_lark_event(text="crash me", chat_type="p2p")
        resp = client.post("/webhook", json=event)
        assert resp.status_code == 200

        await _wait_for_mock_call(mocks["reply_message"])
        assert mocks["reply_message"].called or mocks["send_message"].called


# === Status & Validation ===


def test_status_endpoint():
    agent = _make_agent_mock()
    with _mock_lark_client():
        app = _build_app(agent)
        client = TestClient(app)
        resp = client.get("/status")
        assert resp.status_code == 200
        assert resp.json() == {"status": "available"}


def test_attach_routes_no_entity_raises():
    from agno.os.interfaces.lark.router import attach_routes

    router = APIRouter()
    with pytest.raises(ValueError, match="Either agent, team, or workflow"):
        attach_routes(router, app_id="cli_test", app_secret="secret")


def test_duplicate_event_id_ignored():
    agent = _make_agent_mock()
    with _mock_lark_client():
        app = _build_app(agent, streaming=False)
        client = TestClient(app)
        event = _make_lark_event(text="dup", chat_type="p2p")
        resp1 = client.post("/webhook", json=event)
        resp2 = client.post("/webhook", json=event)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "duplicate"


# === Session Behavior ===


@pytest.mark.asyncio
async def test_same_chat_same_session_id():
    agent = _make_agent_mock()
    with _mock_lark_client():
        app = _build_app(agent, streaming=False)
        client = TestClient(app)

        event1 = _make_lark_event(text="first", chat_type="p2p", message_id="om_1")
        client.post("/webhook", json=event1)
        await _wait_for_agent_call(agent)
        first_session = agent.arun.call_args.kwargs["session_id"]

        agent.arun.reset_mock()
        event2 = _make_lark_event(text="second", chat_type="p2p", message_id="om_2")
        client.post("/webhook", json=event2)
        await _wait_for_agent_call(agent)
        second_session = agent.arun.call_args.kwargs["session_id"]

        assert first_session == second_session
        assert first_session == "lark:test_agent:oc_test"


@pytest.mark.asyncio
async def test_different_chats_different_session_ids():
    agent = _make_agent_mock()
    with _mock_lark_client():
        app = _build_app(agent, streaming=False)
        client = TestClient(app)

        event_a = _make_lark_event(text="hi", chat_type="p2p", chat_id="oc_a")
        client.post("/webhook", json=event_a)
        await _wait_for_agent_call(agent)
        session_a = agent.arun.call_args.kwargs["session_id"]

        agent.arun.reset_mock()
        event_b = _make_lark_event(text="hi", chat_type="p2p", chat_id="oc_b")
        client.post("/webhook", json=event_b)
        await _wait_for_agent_call(agent)
        session_b = agent.arun.call_args.kwargs["session_id"]

        assert session_a != session_b


def call_args_text(agent_mock):
    return agent_mock.arun.call_args[0][0]
