from pathlib import Path
from typing import Any, Optional

from pydantic import Field

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.utils.log import logger


class S3Object(AwsResource):
    """
    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/object/index.html
    """

    resource_type: str = "s3"
    service_name: str = "s3"

    # The Object’s bucket_name identifier. This must be set.
    bucket_name: str
    # The Object’s key identifier. This must be set.
    name: str = Field(..., alias="key")

    @property
    def uri(self) -> str:
        """Returns the URI of the s3.Object

        Returns:
            str: The URI of the s3.Object
        """
        return f"s3://{self.bucket_name}/{self.name}"

    def get_resource(self, aws_client: Optional[AwsApiClient] = None) -> Any:
        """Returns the s3.Object

        Args:
            aws_client: The AwsApiClient for the current cluster

        Returns:
            The s3.Object
        """
        client: AwsApiClient = aws_client or self.get_aws_client()
        service_resource = self.get_service_resource(client)
        return service_resource.Object(
            bucket_name=self.bucket_name,
            key=self.name,
        )

    def download(self, path: Path, aws_client: Optional[AwsApiClient] = None) -> None:
        """Downloads the s3.Object to the specified path

        Args:
            path: The path to download the s3.Object to
            aws_client: The AwsApiClient for the current cluster
        """
        logger.info(f"Downloading {self.uri} to {path}")
        object_resource = self.get_resource(aws_client=aws_client)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open(mode="wb") as f:
            object_resource.download_fileobj(f)
