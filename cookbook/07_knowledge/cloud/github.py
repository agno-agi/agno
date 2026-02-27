"""
GitHub Content Source for Knowledge
====================================

Load files and folders from GitHub repositories into your Knowledge base.
Supports both public and private repositories.

Authentication methods:
- Personal Access Token (PAT): simple, set ``token``
- GitHub App: enterprise-grade, set ``app_id``, ``installation_id``, ``private_key``

Features:
- Load single files or entire folders recursively
- Works with public repos (no token needed) or private repos (token required)
- Automatic file type detection and reader selection
- Rich metadata stored for each file (repo, branch, path)

Requirements:
- For private repos with PAT: GitHub fine-grained PAT with "Contents: read" permission
- For GitHub App auth: ``pip install PyJWT cryptography``

Usage:
    1. Configure GitHubConfig with repo and auth credentials
    2. Register the config on Knowledge via content_sources
    3. Use .file() or .folder() to create content references
    4. Insert into knowledge with knowledge.insert()

Run this cookbook:
    python cookbook/07_knowledge/cloud/github.py
"""

from os import getenv

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import GitHubConfig
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Option 1: Personal Access Token authentication
# ---------------------------------------------------------------------------
# For private repos, set GITHUB_TOKEN env var to a fine-grained PAT with "Contents: read"
github_config = GitHubConfig(
    id="my-repo",
    name="My Repository",
    repo="private/repo",  # Format: owner/repo
    token=getenv("GITHUB_TOKEN"),  # Optional for public repos
    branch="main",  # Default branch
)

# ---------------------------------------------------------------------------
# Option 2: GitHub App authentication
# ---------------------------------------------------------------------------
# For organizations using GitHub Apps instead of personal tokens.
# Requires: pip install PyJWT cryptography
github_app_config = GitHubConfig(
    id="org-repo",
    name="Org Repository",
    repo="my-org/private-repo",
    app_id=getenv("GITHUB_APP_ID"),
    installation_id=getenv("GITHUB_INSTALLATION_ID"),
    private_key=getenv("GITHUB_APP_PRIVATE_KEY"),
    branch="main",
)

# Create Knowledge with GitHub as a content source
knowledge = Knowledge(
    name="GitHub Knowledge",
    vector_db=PgVector(
        table_name="github_knowledge",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    ),
    content_sources=[github_config],
)

if __name__ == "__main__":
    # Insert a single file
    print("Inserting single file from GitHub...")
    knowledge.insert(
        name="README",
        remote_content=github_config.file("README.md"),
    )

    # Insert an entire folder (recursive)
    # Use trailing slash or just the folder name - both work
    print("Inserting folder from GitHub...")
    knowledge.insert(
        name="Cookbook Examples",
        remote_content=github_config.folder("cookbook/01_basics"),
    )

    # Insert from a different branch
    print("Inserting from specific branch...")
    knowledge.insert(
        name="Dev Docs",
        remote_content=github_config.file("docs/index.md", branch="dev"),
    )
