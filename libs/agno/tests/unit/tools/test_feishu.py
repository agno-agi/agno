import json
import time
from unittest.mock import Mock, patch

import pytest

from agno.tools.feishu import FEISHU_BASE_URL, FeishuAPIError, FeishuTools

ENV = {
    "FEISHU_APP_ID": "cli_test_app",
    "FEISHU_APP_SECRET": "test-secret",
}

ALL_TOOLS = ("send_message", "get_chat", "list_chats", "get_user", "reply_message", "delete_message")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("FEISHU_BASE_URL", raising=False)


# === Initialization ===


def test_init_requires_app_id(monkeypatch):
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    with pytest.raises(ValueError, match="FEISHU_APP_ID"):
        FeishuTools()


def test_init_requires_app_secret(monkeypatch):
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)
    with pytest.raises(ValueError, match="FEISHU_APP_SECRET"):
        FeishuTools()


def test_params_override_env():
    tools = FeishuTools(app_id="cli_param", app_secret="param-secret")
    assert tools.app_id == "cli_param"
    assert tools.app_secret == "param-secret"


def test_default_base_url():
    tools = FeishuTools()
    assert tools.base_url == FEISHU_BASE_URL


def test_custom_base_url_strips_trailing_slash():
    tools = FeishuTools(base_url="https://open.larksuite.com/")
    assert tools.base_url == "https://open.larksuite.com"


def test_timeout_forwarded_to_toolkit():
    tools = FeishuTools(timeout=5)
    assert tools.timeout == 5


# === Tool registration ===


def test_default_registers_four_tools():
    tools = FeishuTools()
    names = list(tools.functions.keys())
    assert names == ["send_message", "get_chat", "list_chats", "get_user"]


def test_reply_and_delete_disabled_by_default():
    tools = FeishuTools()
    assert "reply_message" not in tools.functions
    assert "delete_message" not in tools.functions


def test_enable_reply_message():
    tools = FeishuTools(enable_reply_message=True)
    assert "reply_message" in tools.functions
    assert "delete_message" not in tools.functions


def test_enable_delete_message():
    tools = FeishuTools(enable_delete_message=True)
    assert "delete_message" in tools.functions


def test_all_flag_enables_everything():
    tools = FeishuTools(all=True)
    for name in ALL_TOOLS:
        assert name in tools.functions
    assert len(tools.functions) == len(ALL_TOOLS)


def test_disable_send_message():
    tools = FeishuTools(enable_send_message=False)
    assert "send_message" not in tools.functions
    assert len(tools.functions) == 3


def test_no_tools_when_all_disabled():
    tools = FeishuTools(
        enable_send_message=False,
        enable_get_chat=False,
        enable_list_chats=False,
        enable_get_user=False,
    )
    assert len(tools.functions) == 0


# === Helpers: token cache and _request ===


def _response(payload, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    response.raise_for_status = Mock()
    return response


TOKEN_PAYLOAD = {"code": 0, "msg": "ok", "tenant_access_token": "t-abc", "expire": 7200}


@pytest.fixture
def mock_httpx():
    with patch("agno.tools.feishu.httpx") as mocked:
        mocked.post.return_value = _response(TOKEN_PAYLOAD)
        mocked.request.return_value = _response({"code": 0, "msg": "success", "data": {"ok": True}})
        yield mocked


def test_token_is_fetched_with_credentials(mock_httpx):
    tools = FeishuTools(timeout=7)
    token = tools._get_tenant_access_token()
    assert token == "t-abc"
    mock_httpx.post.assert_called_once_with(
        f"{FEISHU_BASE_URL}/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": ENV["FEISHU_APP_ID"], "app_secret": ENV["FEISHU_APP_SECRET"]},
        timeout=7,
    )


def test_token_is_cached_until_refresh_time(mock_httpx):
    tools = FeishuTools()
    tools._get_tenant_access_token()
    tools._get_tenant_access_token()
    assert mock_httpx.post.call_count == 1
    # Refresh is scheduled a safety margin before Feishu's expiry.
    assert tools._token_refresh_at <= time.time() + 7200 - 60


def test_token_is_refreshed_after_refresh_time(mock_httpx):
    tools = FeishuTools()
    tools._get_tenant_access_token()
    tools._token_refresh_at = time.time() - 1
    mock_httpx.post.return_value = _response({**TOKEN_PAYLOAD, "tenant_access_token": "t-new"})
    assert tools._get_tenant_access_token() == "t-new"
    assert mock_httpx.post.call_count == 2


def test_token_business_error_raises(mock_httpx):
    mock_httpx.post.return_value = _response({"code": 10003, "msg": "invalid app_secret"})
    tools = FeishuTools()
    with pytest.raises(FeishuAPIError, match="10003") as exc_info:
        tools._get_tenant_access_token()
    assert exc_info.value.code == 10003
    assert tools._tenant_access_token is None


def test_token_missing_in_payload_raises(mock_httpx):
    mock_httpx.post.return_value = _response({"code": 0, "msg": "ok"})
    tools = FeishuTools()
    with pytest.raises(FeishuAPIError, match="tenant_access_token"):
        tools._get_tenant_access_token()


def test_token_http_error_propagates(mock_httpx):
    mock_httpx.post.return_value.raise_for_status.side_effect = RuntimeError("503 Service Unavailable")
    tools = FeishuTools()
    with pytest.raises(RuntimeError, match="503"):
        tools._get_tenant_access_token()


def test_request_adds_bearer_token_and_base_url(mock_httpx):
    tools = FeishuTools(base_url="https://open.larksuite.com/", timeout=9)
    data = tools._request("GET", "/open-apis/im/v1/chats/oc_1", params={"user_id_type": "open_id"})
    assert data == {"ok": True}
    mock_httpx.request.assert_called_once_with(
        "GET",
        "https://open.larksuite.com/open-apis/im/v1/chats/oc_1",
        params={"user_id_type": "open_id"},
        json=None,
        headers={"Authorization": "Bearer t-abc", "Content-Type": "application/json; charset=utf-8"},
        timeout=9,
    )


def test_request_passes_json_body(mock_httpx):
    tools = FeishuTools()
    tools._request("POST", "/open-apis/im/v1/messages", json_body={"receive_id": "oc_1"})
    assert mock_httpx.request.call_args.kwargs["json"] == {"receive_id": "oc_1"}


def test_request_business_error_raises(mock_httpx):
    mock_httpx.request.return_value = _response({"code": 230002, "msg": "bot not in chat"})
    tools = FeishuTools()
    with pytest.raises(FeishuAPIError, match="230002") as exc_info:
        tools._request("GET", "/open-apis/im/v1/chats/oc_1")
    assert exc_info.value.msg == "bot not in chat"


def test_request_http_error_propagates(mock_httpx):
    mock_httpx.request.return_value.raise_for_status.side_effect = RuntimeError("401 Unauthorized")
    tools = FeishuTools()
    with pytest.raises(RuntimeError, match="401"):
        tools._request("GET", "/open-apis/im/v1/chats/oc_1")


def test_request_returns_empty_dict_when_data_missing(mock_httpx):
    mock_httpx.request.return_value = _response({"code": 0, "msg": "success"})
    tools = FeishuTools()
    assert tools._request("DELETE", "/open-apis/im/v1/messages/om_1") == {}


def test_request_reuses_cached_token_across_calls(mock_httpx):
    tools = FeishuTools()
    tools._request("GET", "/open-apis/im/v1/chats/oc_1")
    tools._request("GET", "/open-apis/im/v1/chats/oc_2")
    assert mock_httpx.post.call_count == 1
    assert mock_httpx.request.call_count == 2


# === Tools ===


def _set_data(mock_httpx, data):
    mock_httpx.request.return_value = _response({"code": 0, "msg": "success", "data": data})


def _last_call(mock_httpx):
    call = mock_httpx.request.call_args
    return call.args[0], call.args[1], call.kwargs


def test_send_message_posts_text_with_default_receive_id_type(mock_httpx):
    _set_data(mock_httpx, {"message_id": "om_1", "chat_id": "oc_1"})
    tools = FeishuTools()

    result = json.loads(tools.send_message(receive_id="oc_1", text="hello"))

    assert result == {"status": "success", "message_id": "om_1", "chat_id": "oc_1"}
    method, url, kwargs = _last_call(mock_httpx)
    assert method == "POST"
    assert url == f"{FEISHU_BASE_URL}/open-apis/im/v1/messages"
    assert kwargs["params"] == {"receive_id_type": "chat_id"}
    body = kwargs["json"]
    assert body["receive_id"] == "oc_1"
    assert body["msg_type"] == "text"
    # Feishu requires `content` to be a JSON-encoded string, not a nested object.
    assert isinstance(body["content"], str)
    assert json.loads(body["content"]) == {"text": "hello"}


def test_send_message_receive_id_type_override(mock_httpx):
    _set_data(mock_httpx, {"message_id": "om_1"})
    tools = FeishuTools(receive_id_type="open_id")

    tools.send_message(receive_id="ou_1", text="hi")
    assert _last_call(mock_httpx)[2]["params"] == {"receive_id_type": "open_id"}

    tools.send_message(receive_id="a@b.com", text="hi", receive_id_type="email")
    assert _last_call(mock_httpx)[2]["params"] == {"receive_id_type": "email"}


def test_send_message_business_error_returns_error_payload(mock_httpx):
    mock_httpx.request.return_value = _response({"code": 230002, "msg": "bot not in chat"})
    tools = FeishuTools()

    result = json.loads(tools.send_message(receive_id="oc_1", text="hello"))

    assert result["status"] == "error"
    assert "230002" in result["message"]
    assert "bot not in chat" in result["message"]


def test_send_message_transport_error_does_not_raise(mock_httpx):
    mock_httpx.request.side_effect = RuntimeError("connection reset")
    tools = FeishuTools()

    result = json.loads(tools.send_message(receive_id="oc_1", text="hello"))

    assert result == {"status": "error", "message": "connection reset"}


def test_reply_message_posts_to_reply_path(mock_httpx):
    _set_data(mock_httpx, {"message_id": "om_2"})
    tools = FeishuTools(enable_reply_message=True)

    result = json.loads(tools.reply_message(message_id="om_1", text="thanks"))

    assert result == {"status": "success", "message_id": "om_2"}
    method, url, kwargs = _last_call(mock_httpx)
    assert method == "POST"
    assert url == f"{FEISHU_BASE_URL}/open-apis/im/v1/messages/om_1/reply"
    assert kwargs["params"] is None
    assert kwargs["json"]["msg_type"] == "text"
    assert json.loads(kwargs["json"]["content"]) == {"text": "thanks"}


def test_delete_message_sends_delete(mock_httpx):
    _set_data(mock_httpx, {})
    tools = FeishuTools(enable_delete_message=True)

    result = json.loads(tools.delete_message(message_id="om_1"))

    assert result == {"status": "success", "deleted": True, "message_id": "om_1"}
    method, url, kwargs = _last_call(mock_httpx)
    assert method == "DELETE"
    assert url == f"{FEISHU_BASE_URL}/open-apis/im/v1/messages/om_1"
    assert kwargs["json"] is None


def test_delete_message_error(mock_httpx):
    mock_httpx.request.return_value = _response({"code": 230011, "msg": "cannot recall others' messages"})
    tools = FeishuTools(enable_delete_message=True)

    result = json.loads(tools.delete_message(message_id="om_1"))

    assert result["status"] == "error"
    assert "230011" in result["message"]


def test_get_chat_flattens_chat_fields(mock_httpx):
    _set_data(mock_httpx, {"name": "Dev Team", "description": "daily sync", "owner_id": "ou_9"})
    tools = FeishuTools()

    result = json.loads(tools.get_chat(chat_id="oc_1"))

    assert result == {"status": "success", "name": "Dev Team", "description": "daily sync", "owner_id": "ou_9"}
    method, url, _ = _last_call(mock_httpx)
    assert method == "GET"
    assert url == f"{FEISHU_BASE_URL}/open-apis/im/v1/chats/oc_1"


def test_get_chat_error(mock_httpx):
    mock_httpx.request.return_value = _response({"code": 232009, "msg": "chat not found"})
    tools = FeishuTools()

    result = json.loads(tools.get_chat(chat_id="oc_missing"))

    assert result["status"] == "error"
    assert "chat not found" in result["message"]


def test_list_chats_returns_items_and_next_page_token(mock_httpx):
    _set_data(
        mock_httpx,
        {
            "items": [{"chat_id": "oc_1", "name": "A"}, {"chat_id": "oc_2", "name": "B"}],
            "has_more": True,
            "page_token": "next-1",
        },
    )
    tools = FeishuTools()

    result = json.loads(tools.list_chats(page_size=2))

    assert result["status"] == "success"
    assert [c["chat_id"] for c in result["items"]] == ["oc_1", "oc_2"]
    assert result["has_more"] is True
    # The token returned is the one for the *next* page, not the one passed in.
    assert result["page_token"] == "next-1"
    method, url, kwargs = _last_call(mock_httpx)
    assert method == "GET"
    assert url == f"{FEISHU_BASE_URL}/open-apis/im/v1/chats"
    assert kwargs["params"] == {"page_size": 2, "page_token": None}


def test_list_chats_passes_page_token(mock_httpx):
    _set_data(mock_httpx, {"items": [], "has_more": False, "page_token": ""})
    tools = FeishuTools()

    result = json.loads(tools.list_chats(page_size=50, page_token="next-1"))

    assert result["has_more"] is False
    assert _last_call(mock_httpx)[2]["params"] == {"page_size": 50, "page_token": "next-1"}


def test_get_user_returns_user_object(mock_httpx):
    _set_data(mock_httpx, {"user": {"name": "Alice", "open_id": "ou_1", "email": "alice@example.com"}})
    tools = FeishuTools()

    result = json.loads(tools.get_user(user_id="ou_1"))

    assert result == {"status": "success", "user": {"name": "Alice", "open_id": "ou_1", "email": "alice@example.com"}}
    method, url, kwargs = _last_call(mock_httpx)
    assert method == "GET"
    assert url == f"{FEISHU_BASE_URL}/open-apis/contact/v3/users/ou_1"
    assert kwargs["params"] == {"user_id_type": "open_id"}


def test_get_user_id_type_override(mock_httpx):
    _set_data(mock_httpx, {"user": {"name": "Bob"}})
    tools = FeishuTools()

    tools.get_user(user_id="u_1", user_id_type="user_id")

    assert _last_call(mock_httpx)[2]["params"] == {"user_id_type": "user_id"}


def test_get_user_error(mock_httpx):
    mock_httpx.request.return_value = _response({"code": 99991672, "msg": "permission denied"})
    tools = FeishuTools()

    result = json.loads(tools.get_user(user_id="ou_1"))

    assert result["status"] == "error"
    assert "permission denied" in result["message"]


def test_tools_use_configured_timeout(mock_httpx):
    _set_data(mock_httpx, {"message_id": "om_1"})
    tools = FeishuTools(timeout=3)

    tools.send_message(receive_id="oc_1", text="hello")

    assert _last_call(mock_httpx)[2]["timeout"] == 3
    assert mock_httpx.post.call_args.kwargs["timeout"] == 3
