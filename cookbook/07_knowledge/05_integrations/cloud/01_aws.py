"""
AWS Integration: S3 Content Source
====================================
Load files and folders from S3 buckets into your Knowledge base.
Supports any S3-compatible storage with AWS credentials.

Features:
- Load single files or entire prefixes (folders) recursively
- Automatic file type detection and reader selection
- Metadata tagging per file (bucket, key, region)

Requirements:
- AWS credentials configured (env vars, profile, or IAM role)
- S3 bucket with read access

Environment Variables:
    AWS_ACCESS_KEY_ID     - AWS access key
    AWS_SECRET_ACCESS_KEY - AWS secret key
    AWS_REGION            - AWS region (default: us-east-1)
"""

import asyncio
from os import getenv

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import S3Config
from agno.vectordb.qdrant import Qdrant

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Configure S3 content source
s3_config = S3Config(
    id="my-bucket",
    name="My S3 Bucket",
    bucket_name=getenv("AWS_S3_BUCKET", "my-bucket"),
    region=getenv("AWS_REGION", "us-east-1"),
)

knowledge = Knowledge(
    name="S3 Knowledge",
    vector_db=Qdrant(
        collection="s3_knowledge",
        url="http://localhost:6333",
    ),
    content_sources=[s3_config],
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # Insert a single file from S3
        print("\n" + "=" * 60)
        print("Loading single file from S3")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Report",
            remote_content=s3_config.file("reports/quarterly-report.pdf"),
        )

        # Insert an entire folder (prefix)
        print("\n" + "=" * 60)
        print("Loading folder from S3")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="All Reports",
            remote_content=s3_config.folder("reports/"),
        )

        # Search
        results = knowledge.search("What were the quarterly results?")
        for doc in results:
            print("- %s" % doc.name)

    asyncio.run(main())
