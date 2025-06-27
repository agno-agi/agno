from abc import ABC, abstractmethod


class CloudStorageConfig(ABC):
    @abstractmethod
    def get_config(self):
        pass


class S3Config(CloudStorageConfig):
    def __init__(self, bucket_name: str, key: str):
        self.bucket_name = bucket_name
        self.key = key


class AzureConfig(CloudStorageConfig):
    def __init__(self, container_name: str, key: str):
        self.container_name = container_name
        self.key = key
