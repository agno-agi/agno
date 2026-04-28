"""
GitHub Context Provider — read repos and open PRs via natural language.

Tools exposed:
    query_<id>(question)   Read files, search content, inspect git history
    update_<id>(instruction)   Edit files and open a pull request

The read demo always runs against agno-agi/agno (public).
The write demo only runs if you set GITHUB_WRITE_REPO.

Requires:
    OPENAI_API_KEY

Optional:
    GITHUB_TOKEN        For private repos and push access
    GITHUB_WRITE_REPO   e.g. "your-name/scratch" to enable the write demo
    gh                  GitHub CLI, only needed for PR creation
"""

from __future__ import annotations

import asyncio
import os
import tempfile

from agno.agent import Agent
from agno.context.github import GitHubContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Read provider — points at a small public repo so the demo is
# self-contained. `root` lives under the system temp dir so repeat
# runs don't pile up under your home directory.
# ---------------------------------------------------------------------------
read_root = os.path.join(tempfile.gettempdir(), "agno_github_context_demo")
gh_read = GitHubContextProvider(
    repo="agno-agi/agno",
    root=read_root,
    branch="main",
    id="agno_repo",
    name="Agno repo",
    model=OpenAIResponses(id="gpt-5.4-mini"),
)

read_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=gh_read.get_tools(),
    instructions=gh_read.instructions(),
    markdown=True,
)


async def main() -> None:
    # ---- asetup clones (or fetches) the repo. Required before query/update.
    await gh_read.asetup()
    print(f"\ngh_read.status() = {gh_read.status()}\n")

    # ---- Read path: always runs.
    read_prompt = (
        "Look at the README.md at the repo root and summarize what Agno is "
        "in 2 sentences. Cite the file you read."
    )
    print(f"> {read_prompt}\n")
    await read_agent.aprint_response(read_prompt)

    # ---- Write path: opt in via env var.
    write_repo = os.environ.get("GITHUB_WRITE_REPO")
    if not write_repo:
        print(
            "\n[skipped write demo] Set GITHUB_WRITE_REPO=owner/yours to also "
            "exercise the update path (it opens a small PR)."
        )
        await gh_read.aclose()
        return

    write_root = os.path.join(tempfile.gettempdir(), "agno_github_context_demo_write")
    gh_write = GitHubContextProvider(
        repo=write_repo,
        root=write_root,
        branch="main",
        pr_branch_prefix="agno",
        id="write_target",
        name=f"Write target ({write_repo})",
        model=OpenAIResponses(id="gpt-5.4-mini"),
    )
    await gh_write.asetup()

    write_agent = Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        tools=gh_write.get_tools(),
        instructions=gh_write.instructions(),
        markdown=True,
    )

    write_prompt = (
        "Append a single line `<!-- demo: agno-context -->` to the bottom "
        "of README.md, commit it, push the branch, and open a pull request "
        "titled 'Demo: agno-context smoke test'. Then report the PR URL."
    )
    print(f"\n> {write_prompt}\n")
    await write_agent.aprint_response(write_prompt)

    await gh_write.aclose()
    await gh_read.aclose()


if __name__ == "__main__":
    asyncio.run(main())
