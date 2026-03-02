"""
GitHub Content Source for Knowledge
====================================

Load files and folders from GitHub repositories into your Knowledge base,
then query them with an Agent.

Authentication methods:
- Personal Access Token (PAT): simple, set ``token``
- GitHub App: enterprise-grade, set ``app_id``, ``installation_id``, ``private_key``

Requirements:
- PostgreSQL with pgvector: ``./cookbook/scripts/run_pgvector.sh``
- For private repos with PAT: GitHub fine-grained PAT with "Contents: read" permission
- For GitHub App auth: ``pip install PyJWT cryptography``

Run this cookbook:
    python cookbook/07_knowledge/cloud/github.py
"""

from os import getenv

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import GitHubConfig
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Option 1: Personal Access Token authentication
# ---------------------------------------------------------------------------
# For private repos, set GITHUB_TOKEN env var to a fine-grained PAT with "Contents: read"
github_config = GitHubConfig(
    id="my-repo",
    name="My Repository",
    repo="owner/repo",  # Format: owner/repo
    token=getenv("GITHUB_TOKEN"),  # Optional for public repos
    branch="main",
)

# ---------------------------------------------------------------------------
# Option 2: GitHub App authentication
# ---------------------------------------------------------------------------
# For organizations using GitHub Apps instead of personal tokens.
# Requires: pip install PyJWT cryptography
#
# github_config = GitHubConfig(
#     id="org-repo",
#     name="Org Repository",
#     repo="owner/repo",
#     app_id=getenv("GITHUB_APP_ID"),
#     installation_id=getenv("GITHUB_INSTALLATION_ID"),
#     private_key=getenv("GITHUB_APP_PRIVATE_KEY"),
#     branch="main",
# )

# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------
knowledge = Knowledge(
    name="GitHub Knowledge",
    vector_db=PgVector(
        table_name="github_knowledge",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    ),
    content_sources=[github_config],
)

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIChat(id="gpt-5.1"),
    name="GitHub Agent",
    knowledge=knowledge,
    search_knowledge=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Insert a single file
    print("Inserting README from GitHub...")
    knowledge.insert(
        name="README",
        remote_content=github_config.file("README.md"),
    )

    # Insert an entire folder (recursive)
    print("Inserting folder from GitHub...")
    knowledge.insert(
        name="Docs",
        remote_content=github_config.folder("docs"),
    )

    # Query the knowledge base through the agent
    agent.print_response(
        "Summarize what this repository is about based on the README",
        markdown=True,
    )
