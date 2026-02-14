import sys
import types
from unittest.mock import MagicMock


def _install_fake_aiohttp():
    if "aiohttp" not in sys.modules:
        aiohttp_mod = types.ModuleType("aiohttp")
        aiohttp_mod.ClientSession = MagicMock()
        aiohttp_mod.ClientTimeout = MagicMock()
        aiohttp_mod.FormData = MagicMock()
        sys.modules["aiohttp"] = aiohttp_mod


_install_fake_aiohttp()
