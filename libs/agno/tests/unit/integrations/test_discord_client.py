"""Unit tests for the Discord integration (agno.integrations.discord)."""

import inspect

import pytest

pytest.importorskip("discord")

from agno.integrations.discord.client import DiscordClient  # noqa: E402


def test_on_message_reads_attachments_without_blocking_the_event_loop():
    """The async ``on_message`` handler must download attachments without a
    synchronous, blocking network call.

    ``requests.get`` is blocking; calling it inside a coroutine freezes the
    whole asyncio event loop for the duration of the download. The handler must
    instead use discord.py's native async ``await media.read()``.
    """
    # ``on_message`` is a closure defined inside ``_setup_events``; its source
    # is captured when we read the enclosing method's source.
    source = inspect.getsource(DiscordClient._setup_events)

    assert "requests.get(" not in source
    assert "await media.read()" in source


def test_discord_client_module_does_not_import_requests():
    """The blocking ``requests`` dependency is no longer needed in this module."""
    import agno.integrations.discord.client as discord_client

    source = inspect.getsource(discord_client)
    assert "import requests" not in source
