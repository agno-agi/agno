from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agno.tools.telegram import TelegramTools


class TestTelegramToolsInit:
    def test_sync_mode_registers_sync_tool(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        tools = TelegramTools(chat_id=12345)
        tool_names = list(tools.functions.keys())
        assert "send_message" in tool_names
        assert "send_message_async" not in tool_names

    def test_async_mode_registers_async_tool(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        tools = TelegramTools(chat_id=12345, async_mode=True)
        # Async functions go to async_functions dict, not functions
        async_tool_names = list(tools.async_functions.keys())
        sync_tool_names = list(tools.functions.keys())
        assert "send_message_async" in async_tool_names
        assert len(sync_tool_names) == 0

    def test_token_from_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "env-token")
        tools = TelegramTools(chat_id=12345)
        assert tools.token == "env-token"

    def test_token_from_param(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
        tools = TelegramTools(chat_id=12345, token="param-token")
        assert tools.token == "param-token"

    def test_param_token_overrides_env(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "env-token")
        tools = TelegramTools(chat_id=12345, token="param-token")
        assert tools.token == "param-token"

    def test_no_tools_when_disabled(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        tools = TelegramTools(chat_id=12345, enable_send_message=False)
        assert len(tools.functions) == 0


class TestSendMessageSync:
    def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        tools = TelegramTools(chat_id=12345)

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = '{"ok":true,"result":{"message_id":1}}'

        with patch.object(tools, "_call_post_method", return_value=mock_resp):
            result = tools.send_message("Hello")
            assert "ok" in result

    def test_http_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        tools = TelegramTools(chat_id=12345)

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=MagicMock()
        )

        with patch.object(tools, "_call_post_method", return_value=mock_resp):
            result = tools.send_message("Hello")
            assert "error" in result.lower()

    def test_calls_correct_api_endpoint(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "test-token-123")
        tools = TelegramTools(chat_id=99999)

        with patch("agno.tools.telegram.httpx.post") as mock_post:
            mock_post.return_value = MagicMock(text="ok", raise_for_status=MagicMock())
            tools.send_message("Test message")
            mock_post.assert_called_once_with(
                "https://api.telegram.org/bottest-token-123/sendMessage",
                json={"chat_id": 99999, "text": "Test message"},
            )


class TestSendMessageAsync:
    @pytest.mark.asyncio
    async def test_success(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        tools = TelegramTools(chat_id=12345, async_mode=True)

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = '{"ok":true,"result":{"message_id":1}}'

        with patch.object(tools, "_call_post_method_async", new_callable=AsyncMock, return_value=mock_resp):
            result = await tools.send_message_async("Hello async")
            assert "ok" in result

    @pytest.mark.asyncio
    async def test_http_error(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "fake-token")
        tools = TelegramTools(chat_id=12345, async_mode=True)

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=MagicMock()
        )

        with patch.object(tools, "_call_post_method_async", new_callable=AsyncMock, return_value=mock_resp):
            result = await tools.send_message_async("Hello async")
            assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_calls_correct_api_endpoint(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_TOKEN", "test-token-456")
        tools = TelegramTools(chat_id=88888, async_mode=True)

        mock_client = AsyncMock()
        mock_resp = MagicMock(text="ok", raise_for_status=MagicMock())
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agno.tools.telegram.httpx.AsyncClient", return_value=mock_client):
            await tools.send_message_async("Async test")
            mock_client.post.assert_called_once_with(
                "https://api.telegram.org/bottest-token-456/sendMessage",
                json={"chat_id": 88888, "text": "Async test"},
            )
