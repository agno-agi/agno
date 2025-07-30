from abc import ABC, abstractmethod
from typing import Optional

from agno.aws.resource.s3.bucket import S3Bucket
from agno.aws.resource.s3.object import S3Object


class CloudStorageConfig(ABC):
    @abstractmethod
    def get_config(self):
        pass


class S3Config(CloudStorageConfig):
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


class GCSConfig(CloudStorageConfig):
    def __init__(self, bucket_name: str, key: str):
        self.bucket_name = bucket_name
        self.key = key

    def get_config(self):
        return {
            "bucket_name": self.bucket_name,
            "key": self.key,
        }


class AzureConfig(CloudStorageConfig):
    def __init__(self, container_name: str, key: str):
        self.container_name = container_name
        self.key = key

    def get_config(self):
        return {
            "container_name": self.container_name,
            "key": self.key,
        }
