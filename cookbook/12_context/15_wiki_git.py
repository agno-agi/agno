"""
Wiki Context Provider (git backend)
====================================

Same WikiContextProvider as `14_wiki_filesystem.py`, but the wiki
lives in a real git repository. After the write sub-agent returns,
the backend stages, commits with an LLM-summarised one-line message,
rebases onto the remote, and pushes.

Auth is PAT-based (`x-access-token:<TOKEN>@github.com/...`). The token
is registered with a `Scrubber` at construction so it never reaches a
log line — including stderr from a failed git invocation.

This cookbook is env-gated. It runs only when both
`WIKI_REPO_URL` and `WIKI_GITHUB_TOKEN` are set; otherwise it prints
a hint and exits cleanly.

Requires:
    OPENAI_API_KEY
    WIKI_REPO_URL       (https://github.com/<owner>/<repo>.git)
    WIKI_GITHUB_TOKEN   (PAT with contents:write on that repo)

    Optional:
    WIKI_BRANCH         (default: main)
    WIKI_LOCAL_PATH     (default: ./demo-wiki-git/ next to this cookbook;
                         override to clone elsewhere, e.g. /repos/<name>)
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from agno.agent import Agent
from agno.context.wiki import GitBackend, WikiContextProvider
from agno.models.openai import OpenAIResponses

REPO_URL = os.getenv("WIKI_REPO_URL")
TOKEN = os.getenv("WIKI_GITHUB_TOKEN")
BRANCH = os.getenv("WIKI_BRANCH", "main")
# Default the clone path next to the cookbook so a casual run doesn't
# require write access to /repos. The directory is gitignored.
LOCAL_PATH = os.getenv("WIKI_LOCAL_PATH") or str(
    Path(__file__).resolve().parent / "demo-wiki-git"
)

if not REPO_URL or not TOKEN:
    print(
        "Skipping git wiki demo — set WIKI_REPO_URL and WIKI_GITHUB_TOKEN to run.\n"
        "Example:\n"
        "  WIKI_REPO_URL=https://github.com/your-org/your-wiki.git \\\n"
        "  WIKI_GITHUB_TOKEN=ghp_xxx \\\n"
        "  .venvs/demo/bin/python cookbook/12_context/15_wiki_git.py"
    )
    sys.exit(0)

# ---------------------------------------------------------------------------
# Create the provider
# ---------------------------------------------------------------------------
backend = GitBackend(
    repo_url=REPO_URL,
    branch=BRANCH,
    github_token=TOKEN,
    local_path=LOCAL_PATH,
)
wiki = WikiContextProvider(
    id="wiki",
    backend=backend,
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
    await wiki.asetup()
    print(f"\nwiki.status() = {wiki.status()}\n")

    write_prompt = (
        "Add or update notes/onboarding.md with two sections: "
        "Day 1 Setup, and First Week Goals. Keep it under twenty lines."
    )
    print(f"> {write_prompt}\n")
    await agent.aprint_response(write_prompt)

    print()
    read_prompt = "What does the onboarding doc say about Day 1 Setup? Cite the file."
    print(f"> {read_prompt}\n")
    await agent.aprint_response(read_prompt)


if __name__ == "__main__":
    asyncio.run(_run())
