"""
Changelog Generator — summarize recent commits from a GitHub repo.

Uses GitHubContextProvider to read git history and generate a
human-readable changelog. The sub-agent uses gpt-5.4-mini for
cost efficiency while the outer agent uses gpt-5.4 for formatting.

Requires:
    OPENAI_API_KEY

Optional:
    GITHUB_TOKEN   For private repos
"""

from __future__ import annotations

import asyncio
import os
import tempfile

from agno.agent import Agent
from agno.context.github import GitHubContextProvider
from agno.models.openai import OpenAIResponses

repo = os.environ.get("GITHUB_CHANGELOG_REPO", "agno-agi/agno")
root = os.path.join(tempfile.gettempdir(), "agno_changelog_demo")

gh = GitHubContextProvider(
    repo=repo,
    root=root,
    branch="main",
    id="changelog_source",
    name=f"Changelog source ({repo})",
    model=OpenAIResponses(id="gpt-5.4-mini"),
)

changelog_agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=gh.get_tools(),
    instructions=f"""You are a changelog generator for {repo}.

When asked to generate a changelog:
1. Use query_changelog_source to get recent commits
2. Group commits by type (feat, fix, refactor, docs, etc.)
3. Write clear, user-facing descriptions (not commit messages verbatim)
4. Include PR/issue references if mentioned in commits

{gh.instructions()}
""",
    markdown=True,
)


async def main() -> None:
    await gh.asetup()
    print(f"Connected to {repo} @ {gh.status().detail}\n")

    prompt = "Generate a changelog for the last 20 commits. Group by type and write user-friendly descriptions."
    print(f"> {prompt}\n")
    await changelog_agent.aprint_response(prompt)

    await gh.aclose()


if __name__ == "__main__":
    asyncio.run(main())
