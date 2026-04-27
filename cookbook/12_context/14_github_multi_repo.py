"""
Multiple GitHub Context Providers on One Agent

Wire 2-3 GitHubContextProvider instances to a single agent, each exposing
its own `query_<id>` tool. The agent picks the right repo based on the
question.

Requires:
    OPENAI_API_KEY

Optional:
    GITHUB_TOKEN   For private repos or higher rate limits
"""

from __future__ import annotations

import asyncio
import os
import tempfile

from agno.agent import Agent
from agno.context.github import GitHubContextProvider
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Provider model — all sub-agents use the same small model for cost efficiency.
# ---------------------------------------------------------------------------
provider_model = OpenAIResponses(id="gpt-5.4-mini")

# ---------------------------------------------------------------------------
# Provider 1: agno-agi/agno — the Agno framework
# ---------------------------------------------------------------------------
agno_root = os.path.join(tempfile.gettempdir(), "agno_multi_repo_demo", "agno")
gh_agno = GitHubContextProvider(
    repo="agno-agi/agno",
    root=agno_root,
    branch="main",
    id="agno",
    name="Agno repo",
    model=provider_model,
)

# ---------------------------------------------------------------------------
# Provider 2: langchain-ai/langchain — for comparison
# ---------------------------------------------------------------------------
langchain_root = os.path.join(
    tempfile.gettempdir(), "agno_multi_repo_demo", "langchain"
)
gh_langchain = GitHubContextProvider(
    repo="langchain-ai/langchain",
    root=langchain_root,
    branch="master",
    id="langchain",
    name="LangChain repo",
    model=provider_model,
)

# ---------------------------------------------------------------------------
# Provider 3: openai/openai-python — OpenAI's Python SDK
# ---------------------------------------------------------------------------
openai_root = os.path.join(tempfile.gettempdir(), "agno_multi_repo_demo", "openai")
gh_openai = GitHubContextProvider(
    repo="openai/openai-python",
    root=openai_root,
    branch="main",
    id="openai_sdk",
    name="OpenAI Python SDK",
    model=provider_model,
)

# ---------------------------------------------------------------------------
# Compose tools + instructions from all providers
# ---------------------------------------------------------------------------
tools = [*gh_agno.get_tools(), *gh_langchain.get_tools(), *gh_openai.get_tools()]
guidance = "\n".join(
    [gh_agno.instructions(), gh_langchain.instructions(), gh_openai.instructions()]
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=tools,
    instructions=(
        "You have access to three GitHub repositories via their query tools:\n"
        "- `query_agno` for the Agno framework\n"
        "- `query_langchain` for LangChain\n"
        "- `query_openai_sdk` for the OpenAI Python SDK\n\n"
        "Pick the right tool for each question. You may query multiple repos "
        "when comparing approaches.\n\n" + guidance
    ),
    markdown=True,
)


async def main() -> None:
    # Setup all providers (clones or fetches each repo)
    print("Setting up providers (this may take a minute on first run)...")
    await asyncio.gather(gh_agno.asetup(), gh_langchain.asetup(), gh_openai.asetup())

    print(f"\ngh_agno.status()      = {gh_agno.status()}")
    print(f"gh_langchain.status() = {gh_langchain.status()}")
    print(f"gh_openai.status()    = {gh_openai.status()}\n")

    # Query: compare how repos structure their main entry point
    prompt = (
        "Compare how Agno and the OpenAI Python SDK define their main Agent/Client "
        "class. For each, find the primary class file and describe how the class "
        "is structured (key methods, initialization pattern). Keep it brief."
    )
    print(f"> {prompt}\n")
    await agent.aprint_response(prompt)

    # Cleanup
    await asyncio.gather(gh_agno.aclose(), gh_langchain.aclose(), gh_openai.aclose())


if __name__ == "__main__":
    asyncio.run(main())
