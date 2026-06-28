"""
Agent Card Demo
===============

Fetch and pretty-print the agent card from a running Agno A2A server using
`A2ACardResolver` from the official `a2a-sdk` client package. Use this to
validate the v1-shaped AgentCard (supportedInterfaces, capabilities,
extendedAgentCard, etc.) that your Agno servers advertise.

Prerequisites:
    .venvs/demo/bin/python -m pip install -U "a2a-sdk>=1.0"

Start a target server in another terminal:
    .venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/weather_agent.py

Then run this script (defaults to the weather agent on port 7770; pass a base URL as an argument to point elsewhere):
    .venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/agent_card_demo.py
    .venvs/demo/bin/python cookbook/05_agent_os/interfaces/a2a/multi_agent_a2a/agent_card_demo.py http://localhost:7777/a2a/agents/trip_planner
"""

import asyncio
import json
import sys

import httpx
from a2a.client import A2ACardResolver
from google.protobuf import json_format

DEFAULT_BASE_URL = "http://localhost:7770/a2a/agents/weather-reporter-agent"


async def main(base_url: str) -> None:
    async with httpx.AsyncClient() as http_client:
        resolver = A2ACardResolver(httpx_client=http_client, base_url=base_url)
        card = await resolver.get_agent_card()
        print(f"Agent card from {base_url}/.well-known/agent-card.json:\n")
        print(
            json.dumps(
                json_format.MessageToDict(card, preserving_proto_field_name=False),
                indent=2,
            )
        )


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL
    asyncio.run(main(target))
