from dataclasses import dataclass
from typing import Optional, Union

from agno.cloud.aws.s3.bucket import S3Bucket
from agno.cloud.aws.s3.object import S3Object


@dataclass
class S3Content:
    def __init__(
        self,
        bucket_name: Optional[str] = None,
        bucket: Optional[S3Bucket] = None,
        key: Optional[str] = None,
        object: Optional[S3Object] = None,
        prefix: Optional[str] = None,
        config_id: Optional[str] = None,
    ):
        self.bucket_name = bucket_name
        self.bucket = bucket
        self.key = key
        self.object = object
        self.prefix = prefix
        self.config_id = config_id

        if bucket_name is None and bucket is None:
            raise ValueError("Either bucket_name or bucket must be provided")
        if key is None and object is None and prefix is None:
            raise ValueError("Either key, object, or prefix must be provided")
        if bucket_name is not None and bucket is not None:
            raise ValueError("Either bucket_name or bucket must be provided, not both")
        if sum(x is not None for x in [key, object, prefix]) > 1:
            raise ValueError("Only one of key, object, or prefix should be provided")

        if self.bucket_name is not None:
            self.bucket = S3Bucket(name=self.bucket_name)

    def get_config(self):
        return {
            "bucket_name": self.bucket_name,
            "bucket": self.bucket,
            "key": self.key,
            "object": self.object,
            "prefix": self.prefix,
            "config_id": self.config_id,
        }


@dataclass
class GCSContent:
    def __init__(
        self,
        bucket=None,  # Type hint removed to avoid import issues
        bucket_name: Optional[str] = None,
        blob_name: Optional[str] = None,
        prefix: Optional[str] = None,
        config_id: Optional[str] = None,
    ):
        self.bucket = bucket
        self.bucket_name = bucket_name
        self.blob_name = blob_name
        self.prefix = prefix
        self.config_id = config_id

        if self.bucket is None and self.bucket_name is None:
            raise ValueError("No bucket or bucket_name provided")
        if self.bucket is not None and self.bucket_name is not None:
            raise ValueError("Provide either bucket or bucket_name")
        if self.blob_name is None and self.prefix is None:
            raise ValueError("Either blob_name or prefix must be provided")

    def get_config(self):
        return {
            "bucket": self.bucket,
            "bucket_name": self.bucket_name,
            "blob_name": self.blob_name,
            "prefix": self.prefix,
            "config_id": self.config_id,
        }


@dataclass
class SharePointContent:
    """Content reference for SharePoint files."""

    def __init__(
        self,
        config_id: str,
        file_path: Optional[str] = None,
        folder_path: Optional[str] = None,
        site_path: Optional[str] = None,
        drive_id: Optional[str] = None,
    ):
        self.config_id = config_id
        self.file_path = file_path
        self.folder_path = folder_path
        self.site_path = site_path
        self.drive_id = drive_id

        if self.file_path is None and self.folder_path is None:
            raise ValueError("Either file_path or folder_path must be provided")
        if self.file_path is not None and self.folder_path is not None:
            raise ValueError("Provide either file_path or folder_path, not both")

    def get_config(self):
        return {
            "config_id": self.config_id,
            "file_path": self.file_path,
            "folder_path": self.folder_path,
            "site_path": self.site_path,
            "drive_id": self.drive_id,
        }


@dataclass
class GitHubContent:
    """Content reference for GitHub files."""

    def __init__(
        self,
        config_id: str,
        file_path: Optional[str] = None,
        folder_path: Optional[str] = None,
        branch: Optional[str] = None,
    ):
        self.config_id = config_id
        self.file_path = file_path
        self.folder_path = folder_path
        self.branch = branch

        if self.file_path is None and self.folder_path is None:
            raise ValueError("Either file_path or folder_path must be provided")
        if self.file_path is not None and self.folder_path is not None:
            raise ValueError("Provide either file_path or folder_path, not both")

    def get_config(self):
        return {
            "config_id": self.config_id,
            "file_path": self.file_path,
            "folder_path": self.folder_path,
            "branch": self.branch,
        }


@dataclass
class AzureBlobContent:
    """Content reference for Azure Blob Storage files.

    Used with AzureBlobConfig to load files from Azure Blob Storage containers.
    Supports loading single blobs or entire prefixes (folders).
    """

    def __init__(
        self,
        config_id: str,
        blob_name: Optional[str] = None,
        prefix: Optional[str] = None,
    ):
        self.config_id = config_id
        self.blob_name = blob_name
        self.prefix = prefix

        if self.blob_name is None and self.prefix is None:
            raise ValueError("Either blob_name or prefix must be provided")
        if self.blob_name is not None and self.prefix is not None:
            raise ValueError("Provide either blob_name or prefix, not both")

    def get_config(self):
        return {
            "config_id": self.config_id,
            "blob_name": self.blob_name,
            "prefix": self.prefix,
        }


RemoteContent = Union[S3Content, GCSContent, SharePointContent, GitHubContent, AzureBlobContent]
