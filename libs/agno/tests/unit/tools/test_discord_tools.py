import json
import sys
import types
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest


def _install_fake_discord_deps():
    """Stub discord.py and aiohttp so DiscordTools can be imported without the real packages."""
    if "discord" not in sys.modules:
        discord_mod = types.ModuleType("discord")
        discord_mod.Client = MagicMock()
        discord_mod.Intents = MagicMock()
        discord_mod.Webhook = MagicMock()
        discord_mod.File = MagicMock()
        sys.modules["discord"] = discord_mod

    if "aiohttp" not in sys.modules:
        aiohttp_mod = types.ModuleType("aiohttp")
        aiohttp_mod.ClientSession = MagicMock()
        aiohttp_mod.ClientTimeout = MagicMock()
        sys.modules["aiohttp"] = aiohttp_mod


_install_fake_discord_deps()

from agno.tools.discord import DiscordTools  # noqa: E402

# --- Initialization ---


class TestInit:
    def test_sync_mode_requires_token(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="bot token is required"):
                DiscordTools(async_mode=False)

    def test_async_mode_warns_without_token(self):
        with patch.dict("os.environ", {}, clear=True):
            tools = DiscordTools(async_mode=True)
            assert tools.bot_token is None

    def test_sync_mode_registers_sync_tools(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "test-token"}):
            tools = DiscordTools(async_mode=False)
            names = [f.name for f in tools.functions.values()]
            assert "send_message" in names
            assert "send_message_async" not in names
            assert len(names) == 5

    def test_async_mode_registers_async_tools(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "test-token"}):
            tools = DiscordTools(async_mode=True)
            names = [f.name for f in tools.async_functions.values()]
            assert "send_message_async" in names
            assert "send_message" not in names
            assert len(names) == 5

    def test_token_from_env(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "env-token"}):
            tools = DiscordTools(async_mode=False)
            assert tools.bot_token == "env-token"

    def test_token_from_param_overrides_env(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "env-token"}):
            tools = DiscordTools(bot_token="param-token", async_mode=False)
            assert tools.bot_token == "param-token"

    def test_selective_tool_registration(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "test-token"}):
            tools = DiscordTools(
                async_mode=False,
                enable_send_message=True,
                enable_get_channel_messages=False,
                enable_get_channel_info=False,
                enable_list_channels=False,
                enable_delete_message=False,
            )
            names = [f.name for f in tools.functions.values()]
            assert names == ["send_message"]


# --- Sync channel tools ---


class TestSyncTools:
    @pytest.fixture
    def tools(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "test-token"}):
            return DiscordTools(async_mode=False)

    def test_send_message_success(self, tools):
        with patch("agno.tools.discord.requests.request") as mock_req:
            mock_req.return_value = Mock(status_code=200, text='{"id":"1"}')
            mock_req.return_value.raise_for_status = Mock()
            mock_req.return_value.json.return_value = {"id": "1"}
            result = tools.send_message("ch1", "Hello")
        assert "successfully" in result

    def test_send_message_error(self, tools):
        with patch("agno.tools.discord.requests.request") as mock_req:
            mock_req.side_effect = Exception("Network error")
            result = tools.send_message("ch1", "Hello")
        assert "Error" in result

    def test_get_channel_info(self, tools):
        with patch("agno.tools.discord.requests.request") as mock_req:
            mock_req.return_value = Mock(text='{"id":"ch1","name":"general"}')
            mock_req.return_value.raise_for_status = Mock()
            mock_req.return_value.json.return_value = {"id": "ch1", "name": "general"}
            result = tools.get_channel_info("ch1")
        data = json.loads(result)
        assert data["name"] == "general"

    def test_list_channels(self, tools):
        with patch("agno.tools.discord.requests.request") as mock_req:
            mock_req.return_value = Mock(text='[{"id":"ch1"}]')
            mock_req.return_value.raise_for_status = Mock()
            mock_req.return_value.json.return_value = [{"id": "ch1", "name": "general"}]
            result = tools.list_channels("guild1")
        data = json.loads(result)
        assert len(data) == 1

    def test_get_channel_messages(self, tools):
        with patch("agno.tools.discord.requests.request") as mock_req:
            mock_req.return_value = Mock(text='[{"content":"hi"}]')
            mock_req.return_value.raise_for_status = Mock()
            mock_req.return_value.json.return_value = [{"content": "hi", "author": {"id": "u1"}}]
            result = tools.get_channel_messages("ch1", limit=10)
        data = json.loads(result)
        assert data[0]["content"] == "hi"

    def test_delete_message(self, tools):
        with patch("agno.tools.discord.requests.request") as mock_req:
            mock_req.return_value = Mock(text="", status_code=204)
            mock_req.return_value.raise_for_status = Mock()
            mock_req.return_value.json.return_value = {}
            result = tools.delete_message("ch1", "msg1")
        assert "deleted successfully" in result

    def test_request_uses_bot_auth_header(self, tools):
        with patch("agno.tools.discord.requests.request") as mock_req:
            mock_req.return_value = Mock(text="{}")
            mock_req.return_value.raise_for_status = Mock()
            mock_req.return_value.json.return_value = {}
            tools.send_message("ch1", "test")
            call_kwargs = mock_req.call_args
            assert "Bot test-token" in call_kwargs.kwargs.get("headers", {}).get("Authorization", "")


# --- Async channel tools ---


class TestAsyncTools:
    @pytest.fixture
    def tools(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "test-token"}):
            return DiscordTools(async_mode=True)

    @pytest.mark.asyncio
    async def test_send_message_async(self, tools):
        mock_channel = AsyncMock()
        mock_client = AsyncMock()
        mock_client.fetch_channel.return_value = mock_channel

        with patch.object(tools, "_get_client", return_value=mock_client):
            result = await tools.send_message_async("12345", "Hello")

        assert "successfully" in result
        mock_client.fetch_channel.assert_called_once_with(12345)
        mock_channel.send.assert_called_once_with(content="Hello")

    @pytest.mark.asyncio
    async def test_get_channel_info_async(self, tools):
        mock_channel = MagicMock()
        mock_channel.id = 12345
        mock_channel.type = MagicMock(value=0)
        mock_channel.name = "general"
        mock_channel.guild_id = 99999
        mock_channel.topic = "Welcome"
        mock_channel.position = 0
        mock_channel.nsfw = False
        mock_client = AsyncMock()
        mock_client.fetch_channel.return_value = mock_channel

        with patch.object(tools, "_get_client", return_value=mock_client):
            result = await tools.get_channel_info_async("12345")

        data = json.loads(result)
        assert data["name"] == "general"
        assert data["id"] == "12345"

    @pytest.mark.asyncio
    async def test_list_channels_async(self, tools):
        ch1 = MagicMock()
        ch1.id = 1
        ch1.name = "general"
        ch1.type = MagicMock(value=0)
        ch1.position = 0
        ch2 = MagicMock()
        ch2.id = 2
        ch2.name = "random"
        ch2.type = MagicMock(value=0)
        ch2.position = 1

        mock_guild = AsyncMock()
        mock_guild.fetch_channels.return_value = [ch1, ch2]
        mock_client = AsyncMock()
        mock_client.fetch_guild.return_value = mock_guild

        with patch.object(tools, "_get_client", return_value=mock_client):
            result = await tools.list_channels_async("99999")

        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["name"] == "general"
        assert data[1]["name"] == "random"
        mock_client.fetch_guild.assert_called_once_with(99999)

    @pytest.mark.asyncio
    async def test_get_channel_messages_async(self, tools):
        from datetime import datetime, timezone

        msg1 = MagicMock()
        msg1.id = 100
        msg1.content = "Hello"
        mock_author = MagicMock()
        mock_author.id = 1
        mock_author.name = "alice"
        msg1.author = mock_author
        msg1.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)

        mock_channel = MagicMock()

        async def fake_history(limit=100):
            for m in [msg1]:
                yield m

        mock_channel.history = fake_history
        mock_client = AsyncMock()
        mock_client.fetch_channel.return_value = mock_channel

        with patch.object(tools, "_get_client", return_value=mock_client):
            result = await tools.get_channel_messages_async("12345", limit=10)

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["content"] == "Hello"
        assert data[0]["author"]["username"] == "alice"

    @pytest.mark.asyncio
    async def test_delete_message_async(self, tools):
        mock_message = AsyncMock()
        mock_channel = AsyncMock()
        mock_channel.fetch_message.return_value = mock_message
        mock_client = AsyncMock()
        mock_client.fetch_channel.return_value = mock_channel

        with patch.object(tools, "_get_client", return_value=mock_client):
            result = await tools.delete_message_async("12345", "67890")

        assert "deleted successfully" in result
        mock_message.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_error_returns_string(self, tools):
        mock_client = AsyncMock()
        mock_client.fetch_channel.side_effect = Exception("API error")

        with patch.object(tools, "_get_client", return_value=mock_client):
            result = await tools.send_message_async("12345", "Hello")

        assert "Error" in result


# --- Webhook operations ---


class TestWebhookOps:
    @pytest.fixture
    def tools(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "test-token"}):
            return DiscordTools(async_mode=True)

    @pytest.mark.asyncio
    async def test_send_webhook_followup(self, tools):
        mock_webhook = AsyncMock()
        mock_session = MagicMock()

        with (
            patch.object(tools, "_get_aiohttp_session", return_value=mock_session),
            patch("agno.tools.discord.discord.Webhook") as MockWebhook,
        ):
            MockWebhook.from_url.return_value = mock_webhook
            await tools.send_webhook_followup("app1", "token1", "Hello")

        MockWebhook.from_url.assert_called_once()
        mock_webhook.send.assert_called_once_with(content="Hello", ephemeral=False)

    @pytest.mark.asyncio
    async def test_send_webhook_followup_ephemeral(self, tools):
        mock_webhook = AsyncMock()
        mock_session = MagicMock()

        with (
            patch.object(tools, "_get_aiohttp_session", return_value=mock_session),
            patch("agno.tools.discord.discord.Webhook") as MockWebhook,
        ):
            MockWebhook.from_url.return_value = mock_webhook
            await tools.send_webhook_followup("app1", "token1", "Secret", ephemeral=True)

        mock_webhook.send.assert_called_once_with(content="Secret", ephemeral=True)

    @pytest.mark.asyncio
    async def test_edit_webhook_message(self, tools):
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = Mock()

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        mock_ctx.__aexit__.return_value = False

        mock_session = MagicMock()
        mock_session.patch.return_value = mock_ctx

        with patch.object(tools, "_get_aiohttp_session", return_value=mock_session):
            await tools.edit_webhook_message("app1", "token1", "Updated")

        mock_session.patch.assert_called_once()
        call_args = mock_session.patch.call_args
        assert "@original" in call_args[0][0]
        assert call_args[1]["json"]["content"] == "Updated"

    @pytest.mark.asyncio
    async def test_edit_webhook_message_with_components(self, tools):
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = Mock()

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        mock_ctx.__aexit__.return_value = False

        mock_session = MagicMock()
        mock_session.patch.return_value = mock_ctx

        components = [{"type": 1, "components": []}]

        with patch.object(tools, "_get_aiohttp_session", return_value=mock_session):
            await tools.edit_webhook_message("app1", "token1", "HITL", components=components)

        payload = mock_session.patch.call_args[1]["json"]
        assert payload["components"] == components

    @pytest.mark.asyncio
    async def test_download_attachment_async(self, tools):
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = Mock()
        mock_resp.content_length = 1024
        mock_resp.read.return_value = b"file-bytes"

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        mock_ctx.__aexit__.return_value = False

        mock_session = MagicMock()
        mock_session.get.return_value = mock_ctx

        with patch.object(tools, "_get_aiohttp_session", return_value=mock_session):
            result = await tools.download_attachment_async("https://cdn.discordapp.com/file.png")

        assert result == b"file-bytes"

    @pytest.mark.asyncio
    async def test_download_attachment_too_large(self, tools):
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = Mock()
        mock_resp.content_length = 50 * 1024 * 1024  # 50MB

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_resp
        mock_ctx.__aexit__.return_value = False

        mock_session = MagicMock()
        mock_session.get.return_value = mock_ctx

        with patch.object(tools, "_get_aiohttp_session", return_value=mock_session):
            result = await tools.download_attachment_async("https://cdn.discordapp.com/big.zip")

        assert result is None

    @pytest.mark.asyncio
    async def test_upload_webhook_file(self, tools):
        mock_webhook = AsyncMock()
        mock_session = MagicMock()

        with (
            patch.object(tools, "_get_aiohttp_session", return_value=mock_session),
            patch("agno.tools.discord.discord.Webhook") as MockWebhook,
            patch("agno.tools.discord.discord.File") as MockFile,
        ):
            MockWebhook.from_url.return_value = mock_webhook
            mock_file = MagicMock()
            MockFile.return_value = mock_file
            await tools.upload_webhook_file("app1", "token1", "image.png", b"png-data", "image/png")

        MockFile.assert_called_once()
        mock_webhook.send.assert_called_once_with(content="", file=mock_file)


# --- Lazy resource initialization ---


class TestLazyInit:
    @pytest.fixture
    def tools(self):
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "test-token"}):
            return DiscordTools(async_mode=True)

    @pytest.mark.asyncio
    async def test_get_client_creates_once(self, tools):
        mock_client = MagicMock()
        mock_client.login = AsyncMock()

        with patch("agno.tools.discord.discord.Client", return_value=mock_client):
            c1 = await tools._get_client()
            c2 = await tools._get_client()

        assert c1 is c2
        mock_client.login.assert_called_once_with("test-token")

    @pytest.mark.asyncio
    async def test_get_aiohttp_session_creates_once(self, tools):
        mock_session = MagicMock()
        mock_session.closed = False

        with patch("agno.tools.discord.aiohttp.ClientSession", return_value=mock_session):
            s1 = await tools._get_aiohttp_session()
            s2 = await tools._get_aiohttp_session()

        assert s1 is s2

    @pytest.mark.asyncio
    async def test_get_aiohttp_session_recreates_if_closed(self, tools):
        mock_session1 = MagicMock()
        mock_session1.closed = False
        mock_session2 = MagicMock()
        mock_session2.closed = False

        with patch("agno.tools.discord.aiohttp.ClientSession", side_effect=[mock_session1, mock_session2]):
            s1 = await tools._get_aiohttp_session()
            mock_session1.closed = True
            s2 = await tools._get_aiohttp_session()

        assert s1 is not s2
