import pytest

from agno.tools.feishu import FEISHU_BASE_URL, FeishuTools

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
