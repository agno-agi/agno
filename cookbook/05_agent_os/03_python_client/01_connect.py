"""Connect to AgentOS and inspect its configuration.

This example shows both the synchronous ``get_config`` method and its
asynchronous ``aget_config`` twin.

Prerequisites: start ``_server.py`` in another terminal.
Run: .venvs/demo/bin/python cookbook/05_agent_os/03_python_client/01_connect.py
Try: compare the component IDs returned by the sync and async calls.
"""

import asyncio

from agno.client import AgentOSClient
from agno.os.schema import ConfigResponse

BASE_URL = "http://localhost:7778"


# ---------------------------------------------------------------------------
# Create the Client
# ---------------------------------------------------------------------------


def print_config(label: str, config: ConfigResponse) -> None:
    """Print the components advertised by AgentOS."""
    print(f"{label}: {config.name or config.os_id}")
    print(f"Agents: {[agent.id for agent in config.agents]}")
    print(f"Teams: {[team.id for team in config.teams]}")
    print(f"Workflows: {[workflow.id for workflow in config.workflows]}")


def connect_sync() -> None:
    """Use the synchronous discovery method."""
    client = AgentOSClient(base_url=BASE_URL)
    print_config("Synchronous connection", client.get_config())


async def connect_async() -> None:
    """Use the asynchronous discovery method."""
    client = AgentOSClient(base_url=BASE_URL)
    print_config("Asynchronous connection", await client.aget_config())


# ---------------------------------------------------------------------------
# Run the Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    connect_sync()
    asyncio.run(connect_async())
