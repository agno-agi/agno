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
    ):
        self.bucket_name = bucket_name
        self.bucket = bucket
        self.key = key
        self.object = object
        self.prefix = prefix

        if bucket_name is None and bucket is None:
            raise ValueError("Either bucket_name or bucket must be provided")
        if key is None and object is None:
            raise ValueError("Either key or object must be provided")
        if bucket_name is not None and bucket is not None:
            raise ValueError("Either bucket_name or bucket must be provided, not both")
        if key is not None and object is not None:
            raise ValueError("Either key or object must be provided, not both")

        if self.bucket_name is not None:
            self.bucket = S3Bucket(name=self.bucket_name)

    def get_config(self):
        return {
            "bucket_name": self.bucket_name,
            "bucket": self.bucket,
            "key": self.key,
            "object": self.object,
            "prefix": self.prefix,
        }


@dataclass
class GCSContent:
    def __init__(
        self,
        bucket=None,  # Type hint removed to avoid import issues
        bucket_name: Optional[str] = None,
        blob_name: Optional[str] = None,
        prefix: Optional[str] = None,
    ):
        # Import Google Cloud Storage only when actually needed
        try:
            from google.cloud import storage  # type: ignore
        except ImportError:
            raise ImportError(
                "The `google-cloud-storage` package is not installed. Please install it via `pip install google-cloud-storage`."
            )

        self.bucket = bucket
        self.bucket_name = bucket_name
        self.blob_name = blob_name
        self.prefix = prefix

        if self.bucket is None and self.bucket_name is None:
            raise ValueError("No bucket or bucket_name provided")
        if self.bucket is not None and self.bucket_name is not None:
            raise ValueError("Provide either bucket or bucket_name")
        if self.blob_name is None and self.prefix is None:
            raise ValueError("Either blob_name or prefix must be provided")

        if self.bucket is None:
            client = storage.Client()
            self.bucket = client.bucket(self.bucket_name)

    def get_config(self):
        return {
            "bucket": self.bucket,
            "bucket_name": self.bucket_name,
            "blob_name": self.blob_name,
            "prefix": self.prefix,
        }


RemoteContent = Union[S3Content, GCSContent]
