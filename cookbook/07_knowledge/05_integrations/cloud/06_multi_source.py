"""
Multi-Source Remote Content
===========================
Combine multiple remote content sources in a single Knowledge instance.
Sources dispatch by ``config_id`` and write into a shared vector DB.

This cookbook runs end-to-end with only public GitHub access. Additional
providers (S3, GCS, SharePoint, Azure Blob) are registered automatically
when their environment variables are set, otherwise they are skipped.

Features demonstrated:
- Multiple configs of different providers in one ``Knowledge``
- Two GitHub configs with different auth profiles (public + authenticated)
- Per-request ``repo`` override so one stateless GitHub config can serve
  many repositories (``GitHubConfig.repo`` is Optional)
- Cross-source search against the unified vector index

Requirements:
- PostgreSQL with pgvector: ./cookbook/scripts/run_pgvector.sh

Environment Variables (all optional):
    GITHUB_TOKEN              - private GitHub repo access (second config)
    S3_BUCKET_NAME            - enables S3 registration
    AWS_REGION                - S3 region
    GCS_BUCKET_NAME           - enables GCS registration
    GCP_PROJECT               - GCS project
    SHAREPOINT_TENANT_ID      - enables SharePoint registration
    SHAREPOINT_CLIENT_ID
    SHAREPOINT_CLIENT_SECRET
    SHAREPOINT_HOSTNAME
    AZURE_TENANT_ID           - enables Azure Blob registration
    AZURE_CLIENT_ID
    AZURE_CLIENT_SECRET
    AZURE_STORAGE_ACCOUNT
    AZURE_CONTAINER
"""

import asyncio
from os import getenv

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import (
    AzureBlobConfig,
    GcsConfig,
    GitHubConfig,
    S3Config,
    SharePointConfig,
)
from agno.vectordb.pgvector import PgVector

content_sources: list = []

# GitHub: public repos (no token, no default repo).
# One stateless config serves many repos via per-request override.
github_public = GitHubConfig(
    id="github-public",
    name="GitHub (public, dynamic repo)",
    branch="main",
)
content_sources.append(github_public)

# GitHub: authenticated repos (PAT, default repo).
# Only registered when GITHUB_TOKEN is set.
github_private = None
if getenv("GITHUB_TOKEN"):
    github_private = GitHubConfig(
        id="github-private",
        name="GitHub (authenticated)",
        repo=getenv("GITHUB_DEFAULT_REPO", "agno-agi/agno"),
        token=getenv("GITHUB_TOKEN"),
        branch="main",
    )
    content_sources.append(github_private)

# S3: optional.
if getenv("S3_BUCKET_NAME"):
    content_sources.append(
        S3Config(
            id="s3-docs",
            name="S3 Documents",
            bucket_name=getenv("S3_BUCKET_NAME", ""),
            region=getenv("AWS_REGION", "us-east-1"),
        )
    )

# GCS: optional.
if getenv("GCS_BUCKET_NAME"):
    content_sources.append(
        GcsConfig(
            id="gcs-data",
            name="GCS Data",
            bucket_name=getenv("GCS_BUCKET_NAME", ""),
            project=getenv("GCP_PROJECT", ""),
        )
    )

# SharePoint: optional.
if getenv("SHAREPOINT_TENANT_ID"):
    content_sources.append(
        SharePointConfig(
            id="sharepoint-docs",
            name="SharePoint Documents",
            tenant_id=getenv("SHAREPOINT_TENANT_ID", ""),
            client_id=getenv("SHAREPOINT_CLIENT_ID", ""),
            client_secret=getenv("SHAREPOINT_CLIENT_SECRET", ""),
            hostname=getenv("SHAREPOINT_HOSTNAME", ""),
            site_id=getenv("SHAREPOINT_SITE_ID"),
        )
    )

# Azure Blob: optional.
if getenv("AZURE_TENANT_ID"):
    content_sources.append(
        AzureBlobConfig(
            id="azure-blob",
            name="Azure Blob",
            tenant_id=getenv("AZURE_TENANT_ID", ""),
            client_id=getenv("AZURE_CLIENT_ID", ""),
            client_secret=getenv("AZURE_CLIENT_SECRET", ""),
            storage_account=getenv("AZURE_STORAGE_ACCOUNT", ""),
            container=getenv("AZURE_CONTAINER", ""),
        )
    )

knowledge = Knowledge(
    name="Multi-Source Knowledge",
    vector_db=PgVector(
        table_name="multi_source_knowledge",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    ),
    content_sources=content_sources,
)


if __name__ == "__main__":

    async def main():
        print("\n" + "=" * 60)
        print("Registered content sources:")
        print("=" * 60)
        for src in content_sources:
            print("- [%s] %s (%s)" % (src.id, src.name, type(src).__name__))

        # Load two different public repos through one stateless GitHub config.
        # Distinct names to avoid the content_hash collision that occurs when
        # two uploads share the same logical name across different providers.
        print("\n" + "=" * 60)
        print("Loading README.md from agno-agi/agno (github-public)")
        print("=" * 60 + "\n")
        await knowledge.ainsert(
            name="Agno README",
            remote_content=github_public.file("README.md", repo="agno-agi/agno"),
        )

        print("\n" + "=" * 60)
        print("Loading LICENSE from anthropics/anthropic-sdk-python (github-public)")
        print("=" * 60 + "\n")
        await knowledge.ainsert(
            name="Anthropic SDK LICENSE",
            remote_content=github_public.file(
                "LICENSE", repo="anthropics/anthropic-sdk-python"
            ),
        )

        # Load through the authenticated GitHub config if it was registered.
        if github_private is not None:
            print("\n" + "=" * 60)
            print("Loading README.md from default repo (github-private)")
            print("=" * 60 + "\n")
            await knowledge.ainsert(
                name="Private Repo README",
                remote_content=github_private.file("README.md"),
            )

        # Cross-source search against the unified vector index.
        print("\n" + "=" * 60)
        print("Searching across all registered sources")
        print("=" * 60 + "\n")
        results = await knowledge.asearch("What is Agno?")
        for doc in results:
            print("- %s" % doc.name)

    asyncio.run(main())
