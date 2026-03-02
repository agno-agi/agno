"""
GCP Integration: Google Cloud Storage
=======================================
Load files and folders from GCS buckets into your Knowledge base.

Features:
- Load single files or entire prefixes recursively
- Automatic file type detection
- Service account or application default credentials

Requirements:
- GCP credentials configured
- GCS bucket with read access

Environment Variables:
    GOOGLE_APPLICATION_CREDENTIALS - Path to service account key file
    GCS_BUCKET_NAME               - GCS bucket name
"""

import asyncio
from os import getenv

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import GcsConfig
from agno.vectordb.qdrant import Qdrant

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

gcs_config = GcsConfig(
    id="my-gcs-bucket",
    name="My GCS Bucket",
    bucket_name=getenv("GCS_BUCKET_NAME", "my-bucket"),
)

knowledge = Knowledge(
    name="GCS Knowledge",
    vector_db=Qdrant(
        collection="gcs_knowledge",
        url="http://localhost:6333",
    ),
    content_sources=[gcs_config],
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # Single file
        print("\n" + "=" * 60)
        print("GCS: single file")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Report",
            remote_content=gcs_config.file("reports/quarterly.pdf"),
        )

        # Folder
        print("\n" + "=" * 60)
        print("GCS: folder")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="All Reports",
            remote_content=gcs_config.folder("reports/"),
        )

        results = knowledge.search("What were the results?")
        for doc in results:
            print("- %s" % doc.name)

    asyncio.run(main())
