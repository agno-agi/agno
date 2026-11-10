"""
GitHub Integration: Per-Request Repo Override
=============================================
Use a single GitHubConfig with no default repo to load content from
multiple repositories by passing the repo at request time.

GitHubConfig.repo is Optional, and GitHubConfig.file() / .folder() accept
a ``repo`` argument that overrides whatever is on the config. This lets
one configured GitHub source (and its auth credentials, including a
GitHub App installation) serve many repositories.

Features:
- One config, many repos — share auth across multiple sources
- Works for both single files and folders
- Same auth (PAT or GitHub App) applies to every request

Requirements:
- PostgreSQL with pgvector: ./cookbook/scripts/run_pgvector.sh
- For private repos: GITHUB_TOKEN env var with "Contents: read" permission

Environment Variables:
    GITHUB_TOKEN - Optional, for private repos (fine-grained PAT)
"""

import asyncio
from os import getenv

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import GitHubConfig
from agno.vectordb.pgvector import PgVector

github_config = GitHubConfig(
    id="dynamic-repo",
    name="Dynamic GitHub Source",
    token=getenv("GITHUB_TOKEN"),
    branch="main",
)

knowledge = Knowledge(
    name="GitHub Dynamic Repo Knowledge",
    vector_db=PgVector(
        table_name="github_dynamic_repo",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    ),
    content_sources=[github_config],
)


if __name__ == "__main__":

    async def main():
        print("\n" + "=" * 60)
        print("Loading README.md from agno-agi/agno")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Agno README",
            remote_content=github_config.file("README.md", repo="agno-agi/agno"),
        )

        print("\n" + "=" * 60)
        print("Loading LICENSE from anthropics/anthropic-sdk-python")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Anthropic SDK LICENSE",
            remote_content=github_config.file(
                "LICENSE", repo="anthropics/anthropic-sdk-python"
            ),
        )

        print("\n" + "=" * 60)
        print("Searching across both repos")
        print("=" * 60 + "\n")

        results = await knowledge.asearch("What is Agno?")
        for doc in results:
            print("- %s" % doc.name)

    asyncio.run(main())
