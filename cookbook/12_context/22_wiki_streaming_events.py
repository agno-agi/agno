"""
Wiki Context Provider — Sub-Agent Event Streaming
==================================================

When the parent agent calls a context provider's query tool, the
sub-agent's events (tool calls, content) are streamed back automatically.
This is the context-provider equivalent of Team's delegate_task_to_member.

Run with `stream=True` and the UI sees sub-agent activity in real-time.

Requires: OPENAI_API_KEY
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from agno.agent import Agent
from agno.context.wiki import FileSystemBackend, WikiContextProvider
from agno.models.openai import OpenAIResponses

WIKI_PATH = Path(__file__).resolve().parent / "demo-wiki"
if WIKI_PATH.exists():
    shutil.rmtree(WIKI_PATH)
WIKI_PATH.mkdir()
(WIKI_PATH / "README.md").write_text(
    "# Demo Wiki\n\nA tiny wiki for testing sub-agent streaming.\n"
)
(WIKI_PATH / "architecture.md").write_text(
    "# Architecture\n\n"
    "The system uses a three-tier architecture:\n"
    "1. Frontend (React)\n"
    "2. API (FastAPI)\n"
    "3. Database (PostgreSQL)\n"
)

wiki = WikiContextProvider(
    id="wiki",
    backend=FileSystemBackend(path=WIKI_PATH),
    model=OpenAIResponses(id="gpt-5.4-mini"),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=wiki.get_tools(),
    instructions=wiki.instructions(),
    markdown=True,
)


async def main() -> None:
    print(f"\nwiki.status() = {wiki.status()}\n")

    prompt = "What is our system architecture? List the tiers."
    print(f"> {prompt}\n")
    await agent.aprint_response(prompt, stream=True)


if __name__ == "__main__":
    asyncio.run(main())
