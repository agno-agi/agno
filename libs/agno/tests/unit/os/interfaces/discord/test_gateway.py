import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.os.interfaces.discord.processing import strip_mention


def _install_fake_discord():
    if "discord" not in sys.modules:
        discord_mod = types.ModuleType("discord")

        discord_mod.Intents = MagicMock()
        discord_mod.Client = MagicMock()
        discord_mod.Thread = type("Thread", (), {})
        discord_mod.DMChannel = type("DMChannel", (), {})
        discord_mod.TextChannel = type("TextChannel", (), {})
        discord_mod.File = MagicMock()
        discord_mod.ButtonStyle = MagicMock()

        ui_mod = types.ModuleType("discord.ui")
        ui_mod.View = type("View", (), {"__init__": lambda self: None})
        ui_mod.button = MagicMock(return_value=lambda f: f)
        discord_mod.ui = ui_mod
        sys.modules["discord"] = discord_mod
        sys.modules["discord.ui"] = ui_mod


_install_fake_discord()


# strip_mention: same function tested here via the gateway import path
class TestMentionStripping:
    def test_standard_mention(self):
        assert strip_mention("<@123456789> hello world") == "hello world"

    def test_nickname_mention(self):
        assert strip_mention("<@!123456789> hello") == "hello"

    def test_multiple_mentions(self):
        assert strip_mention("<@111> <@!222> hi") == "hi"

    def test_no_mention(self):
        assert strip_mention("just text") == "just text"

    def test_mention_only_returns_empty(self):
        assert strip_mention("<@123>") == ""

    def test_mention_in_middle(self):
        assert strip_mention("hey <@123> there") == "hey  there"


# GatewayReplier wraps channel.send() to satisfy the Replier protocol
class TestGatewayReplier:
    @pytest.fixture
    def mock_channel(self):
        channel = MagicMock()
        channel.send = AsyncMock()
        channel.typing = MagicMock(return_value=MagicMock(__aenter__=AsyncMock(), __aexit__=AsyncMock()))
        return channel

    async def test_send_initial_response(self, mock_channel):
        from agno.os.interfaces.discord.gateway import GatewayReplier

        replier = GatewayReplier(channel=mock_channel)
        await replier.send_initial_response("Hello")
        mock_channel.send.assert_called_once_with("Hello")

    async def test_send_followup(self, mock_channel):
        from agno.os.interfaces.discord.gateway import GatewayReplier

        replier = GatewayReplier(channel=mock_channel)
        await replier.send_followup("Follow-up")
        mock_channel.send.assert_called_once_with("Follow-up")

    async def test_send_media(self, mock_channel):
        from agno.os.interfaces.discord.gateway import GatewayReplier

        replier = GatewayReplier(channel=mock_channel)
        await replier.send_media(b"image-bytes", "test.png")
        mock_channel.send.assert_called_once()
        call_kwargs = mock_channel.send.call_args[1]
        assert "file" in call_kwargs


# Session ID format validation: dc:thread:, dc:dm:, dc:channel::user:
class TestSessionIdScheme:
    def test_thread_session_id(self):
        session_id = "dc:thread:123456"
        assert session_id.startswith("dc:thread:")

    def test_dm_session_id(self):
        session_id = "dc:dm:789012"
        assert session_id.startswith("dc:dm:")

    def test_channel_session_id(self):
        session_id = "dc:channel:456:user:789"
        assert session_id.startswith("dc:channel:")
        assert ":user:" in session_id


# create_gateway_client: requires discord.py at runtime, should raise without it
class TestCreateGatewayClient:
    def test_raises_without_discord(self):
        original_discord = sys.modules.get("discord")
        try:
            with patch("agno.os.interfaces.discord.gateway.discord", None):
                from agno.os.interfaces.discord.gateway import create_gateway_client

                with pytest.raises(ImportError, match="discord.py is required"):
                    create_gateway_client(agent=MagicMock())
        finally:
            if original_discord:
                sys.modules["discord"] = original_discord


# Discord class: gateway auto-activation with/without token and discord.py
class TestDiscordClassGateway:
    def test_no_gateway_without_token(self):
        from agno.os.interfaces.discord.discord import Discord

        with patch.dict("os.environ", {}, clear=True):
            discord_iface = Discord(agent=MagicMock())
            assert discord_iface._gateway_client is None
            assert discord_iface.get_lifespan() is None

    def test_no_gateway_without_discord_package(self):
        from agno.os.interfaces.discord.discord import Discord

        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "test-token"}, clear=False):
            with patch("builtins.__import__", side_effect=_selective_import_error):
                discord_iface = Discord(agent=MagicMock())
                assert discord_iface._gateway_client is None
                assert discord_iface.get_lifespan() is None

    def test_gateway_activates_with_dependencies(self):
        from agno.os.interfaces.discord.discord import Discord

        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": "test-token"}, clear=False):
            with patch("agno.os.interfaces.discord.gateway.create_gateway_client", return_value=MagicMock()):
                discord_iface = Discord(agent=MagicMock())
                assert discord_iface._gateway_client is not None
                lifespan = discord_iface.get_lifespan()
                assert lifespan is not None
                assert callable(lifespan)

    def test_explicit_token_param(self):
        from agno.os.interfaces.discord.discord import Discord

        with patch("agno.os.interfaces.discord.gateway.create_gateway_client", return_value=MagicMock()):
            discord_iface = Discord(agent=MagicMock(), discord_bot_token="explicit-token")
            assert discord_iface._gateway_client is not None
            assert discord_iface._gateway_token == "explicit-token"


def _selective_import_error(name, *args, **kwargs):
    if name == "discord":
        raise ImportError("No module named 'discord'")
    return original_import(name, *args, **kwargs)


original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
