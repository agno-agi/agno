"""
Wiki Context Provider (filesystem backend)
==========================================

WikiContextProvider exposes a directory of markdown files via two tools:
- `query_<id>(question)`     - natural-language reads via a sub-agent
                                with read-only Workspace tools.
- `update_<id>(instruction)` - natural-language writes via a sub-agent
                                with read + write Workspace tools.

The pluggable backend decides what happens to writes after the
sub-agent returns. `FileSystemBackend` does nothing extra: the
directory is the source of truth. Demoable with no auth and no
network.

This cookbook seeds an empty `demo-wiki/` next to the script, asks
the agent to add a deploys runbook, then asks it to read the runbook
back and answer a question.

Requires: OPENAI_API_KEY
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from agno.agent import Agent
from agno.context.wiki import FileSystemBackend, WikiContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Seed an empty wiki directory next to the cookbook
# ---------------------------------------------------------------------------
WIKI_PATH = Path(__file__).resolve().parent / "demo-wiki"
if WIKI_PATH.exists():
    shutil.rmtree(WIKI_PATH)
WIKI_PATH.mkdir()
(WIKI_PATH / "README.md").write_text(
    "# Demo Wiki\n\n"
    "This is a tiny markdown wiki used by the WikiContextProvider cookbook.\n"
    "Pages live under `runbooks/`, `architecture/`, and the root.\n"
)

# ---------------------------------------------------------------------------
# Create the provider
# ---------------------------------------------------------------------------
wiki = WikiContextProvider(
    id="wiki",
    backend=FileSystemBackend(path=WIKI_PATH),
    model=OpenAIResponses(id="gpt-5.4-mini"),
)

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=wiki.get_tools(),
    instructions=wiki.instructions(),
    markdown=True,
)


# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
async def _run() -> None:
    print(f"\nwiki.status() = {wiki.status()}\n")

    write_prompt = (
        "Add a deploys runbook to docs/deploys.md with three sections: "
        "Prerequisites, Steps, and Rollback. Keep it terse."
    )
    print(f"> {write_prompt}\n")
    await agent.aprint_response(write_prompt)

    print()
    read_prompt = "How do we deploy? Cite the file you pulled from."
    print(f"> {read_prompt}\n")
    await agent.aprint_response(read_prompt)

    deploys = WIKI_PATH / "docs" / "deploys.md"
    assert deploys.exists(), f"agent did not write {deploys}"
    print(
        f"\n[ok] wrote {deploys.relative_to(WIKI_PATH)}: {deploys.stat().st_size} bytes"
    )


if __name__ == "__main__":
    asyncio.run(_run())
