import sys
import types
from unittest.mock import MagicMock


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
