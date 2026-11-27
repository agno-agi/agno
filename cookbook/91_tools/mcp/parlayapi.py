"""Inspect ParlayAPI's read-only MCP tools before an optional private agent run.

Install: uv pip install "agno[mcp]==3.0.9" "parlayapi-mcp==0.3.7"
Default: python cookbook/91_tools/mcp/parlayapi.py
The default performs local MCP discovery only, with no API or model calls.
"""

import argparse
import asyncio
import os
import sys
from importlib.metadata import version

from agno.tools.mcp import MCPTools
from mcp import StdioServerParameters

DISCOVERY_TOOLS = [
    "parlayapi_get_pricing",
    "parlayapi_live_sports",
    "parlayapi_source_quality",
    "parlayapi_book_coverage",
]
PRIVATE_TOOLS = ["parlayapi_list_sports", "parlayapi_get_odds", "parlayapi_get_props"]


def make_tools(private: bool = False) -> MCPTools:
    if version("parlayapi-mcp") != "0.3.7":
        raise ValueError(
            "Install parlayapi-mcp==0.3.7 for this reviewed tool allowlist."
        )
    key = ""
    if private:
        key = (os.getenv("PARLAYAPI_KEY") or os.getenv("PARLAY_API_KEY") or "").strip()
        if not key or "\r" in key or "\n" in key:
            raise ValueError(
                "Private mode requires your own valid ParlayAPI key in the environment."
            )
    return MCPTools(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=["-m", "parlayapi_mcp"],
            env={
                "PARLAYAPI_BASE_URL": "https://parlay-api.com",
                "PARLAYAPI_KEY": key,
                "PARLAY_API_KEY": "",
            },
        ),
        include_tools=DISCOVERY_TOOLS + (PRIVATE_TOOLS if private else []),
        timeout_seconds=30,
    )


async def run_example(question: str | None = None, private: bool = False) -> None:
    async with make_tools(private) as tools:
        expected = set(DISCOVERY_TOOLS + (PRIVATE_TOOLS if private else []))
        if set(tools.functions) != expected:
            raise RuntimeError(
                "MCP discovery did not match the reviewed tool allowlist."
            )
        if question is None:
            print("Read-only MCP tools: " + ", ".join(sorted(tools.functions)))
            print("Discovery only. No ParlayAPI endpoint or model was called.")
            return

        from agno.agent import Agent
        from agno.models.openai import OpenAIResponses

        agent = Agent(
            name="Private Sports Data Research",
            model=OpenAIResponses(id="gpt-5.6-luna", max_retries=0),
            tools=[tools],
            tool_call_limit=2,
            telemetry=False,
            instructions=[
                "Use at most two read-only calls. Do not retry failed requests.",
                "Return coverage counts and limitations, not raw odds or participant lists.",
                "Keep missing outcomes and unknown source ages explicit. Never infer complete coverage.",
                "Do not recommend or place bets, create accounts, send emails, or change billing.",
            ],
            markdown=True,
        )
        await agent.aprint_response(question)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--question", help="Explicitly call a model and the permitted discovery tools."
    )
    parser.add_argument(
        "--private",
        action="store_true",
        help="Also permit own-key data tools; usage may be charged.",
    )
    args = parser.parse_args()
    asyncio.run(run_example(args.question, args.private))
