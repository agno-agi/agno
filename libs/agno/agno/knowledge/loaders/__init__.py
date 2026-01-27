"""Remote content loaders for Knowledge.

This module provides loaders for various cloud storage providers:
- S3Loader: AWS S3
- GCSLoader: Google Cloud Storage
- SharePointLoader: Microsoft SharePoint
- GitHubLoader: GitHub repositories
- AzureBlobLoader: Azure Blob Storage
"""

from agno.knowledge.loaders.azure_blob import AzureBlobLoader
from agno.knowledge.loaders.base import RemoteContentLoader
from agno.knowledge.loaders.gcs import GCSLoader
from agno.knowledge.loaders.github import GitHubLoader
from agno.knowledge.loaders.s3 import S3Loader
from agno.knowledge.loaders.sharepoint import SharePointLoader

__all__ = [
    "RemoteContentLoader",
    "S3Loader",
    "GCSLoader",
    "SharePointLoader",
    "GitHubLoader",
    "AzureBlobLoader",
]
