import inspect

from agno.integrations.discord.client import DiscordClient


def test_on_message_does_not_block_event_loop_for_attachments():
    """Regression test: the async ``on_message`` handler must not use the
    synchronous, blocking ``requests.get`` to download attachments.

    A blocking network call inside the coroutine freezes the entire asyncio
    event loop for the duration of the download, stalling every other Discord
    message and concurrent agent run. The fix downloads attachments with
    discord.py's native async ``await media.read()`` instead.
    """
    # ``on_message`` is a closure defined inside ``_setup_events``; its source
    # is included when we read the enclosing method's source.
    source = inspect.getsource(DiscordClient._setup_events)

    # The blocking download must be gone.
    assert "requests.get(" not in source
    # Attachments must be read via the non-blocking, authenticated async API.
    assert "await media.read()" in source


def test_discord_client_module_does_not_import_requests():
    """The blocking ``requests`` dependency is no longer needed in this module."""
    import agno.integrations.discord.client as discord_client

    source = inspect.getsource(discord_client)
    assert "import requests" not in source
