from typing import Any, Dict, List, Optional

from typing_extensions import Literal

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.aws.resource.s3.object import S3Object
from agno.cli.console import print_info
from agno.utils.log import logger


class S3Bucket(AwsResource):
    """
    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#service-resource
    """

    resource_type: str = "s3"
    service_name: str = "s3"

    # Name of the bucket
    name: str
    # The canned ACL to apply to the bucket.
    acl: Optional[Literal["private", "public-read", "public-read-write", "authenticated-read"]] = None
    grant_full_control: Optional[str] = None
    grant_read: Optional[str] = None
    grant_read_ACP: Optional[str] = None
    grant_write: Optional[str] = None
    grant_write_ACP: Optional[str] = None
    object_lock_enabled_for_bucket: Optional[bool] = None
    object_ownership: Optional[Literal["BucketOwnerPreferred", "ObjectWriter", "BucketOwnerEnforced"]] = None

    @property
    def uri(self) -> str:
        """Returns the URI of the s3.Bucket

        Returns:
            str: The URI of the s3.Bucket
        """
        return f"s3://{self.name}"

    def get_resource(self, aws_client: Optional[AwsApiClient] = None) -> Optional[Any]:
        """Returns the s3.Bucket

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        client: AwsApiClient = aws_client or self.get_aws_client()
        service_resource = self.get_service_resource(client)
        return service_resource.Bucket(name=self.name)

    def _create(self, aws_client: AwsApiClient) -> bool:
        """Creates the s3.Bucket

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")

        # Step 1: Build bucket configuration
        # Bucket names are GLOBALLY unique!
        # AWS will give you the IllegalLocationConstraintException if you collide
        # with an already existing bucket if you've specified a region different than
        # the region of the already existing bucket. If you happen to guess the correct region of the
        # existing bucket it will give you the BucketAlreadyExists exception.
        bucket_configuration = None
        if aws_client.aws_region is not None and aws_client.aws_region != "us-east-1":
            bucket_configuration = {"LocationConstraint": aws_client.aws_region}

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}
        if bucket_configuration:
            not_null_args["CreateBucketConfiguration"] = bucket_configuration
        if self.acl:
            not_null_args["ACL"] = self.acl
        if self.grant_full_control:
            not_null_args["GrantFullControl"] = self.grant_full_control
        if self.grant_read:
            not_null_args["GrantRead"] = self.grant_read
        if self.grant_read_ACP:
            not_null_args["GrantReadACP"] = self.grant_read_ACP
        if self.grant_write:
            not_null_args["GrantWrite"] = self.grant_write
        if self.grant_write_ACP:
            not_null_args["GrantWriteACP"] = self.grant_write_ACP
        if self.object_lock_enabled_for_bucket:
            not_null_args["ObjectLockEnabledForBucket"] = self.object_lock_enabled_for_bucket
        if self.object_ownership:
            not_null_args["ObjectOwnership"] = self.object_ownership

        # Step 2: Create Bucket
        service_client = self.get_service_client(aws_client)
        try:
            response = service_client.create_bucket(
                Bucket=self.name,
                **not_null_args,
            )
            logger.debug(f"Response: {response}")
            bucket_location = response.get("Location")
            if bucket_location is not None:
                logger.debug(f"Bucket created: {bucket_location}")
                self.active_resource = response
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def post_create(self, aws_client: AwsApiClient) -> bool:
        # Wait for Bucket to be created
        if self.wait_for_create:
            try:
                print_info(f"Waiting for {self.get_resource_type()} to be created.")
                waiter = self.get_service_client(aws_client).get_waiter("bucket_exists")
                waiter.wait(
                    Bucket=self.name,
                    WaiterConfig={
                        "Delay": self.waiter_delay,
                        "MaxAttempts": self.waiter_max_attempts,
                    },
                )
            except Exception as e:
                logger.error("Waiter failed.")
                logger.error(e)
        return True

    def _read(self, aws_client: AwsApiClient) -> Optional[Any]:
        """Returns the s3.Bucket

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")

        from botocore.exceptions import ClientError

        try:
            service_resource = self.get_service_resource(aws_client)
            bucket = service_resource.Bucket(name=self.name)
            bucket.load()
            creation_date = bucket.creation_date
            logger.debug(f"Bucket creation_date: {creation_date}")
            if creation_date is not None:
                logger.debug(f"Bucket found: {bucket.name}")
                self.active_resource = {
                    "name": bucket.name,
                    "creation_date": creation_date,
                }
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return self.active_resource

    def _delete(self, aws_client: AwsApiClient) -> bool:
        """Deletes the s3.Bucket

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")

        service_client = self.get_service_client(aws_client)
        self.active_resource = None
        try:
            response = service_client.delete_bucket(Bucket=self.name)
            logger.debug(f"Response: {response}")
            return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be deleted.")
            logger.error("Please try again or delete resources manually.")
            logger.error(e)
        return False

    def get_objects(self, aws_client: Optional[AwsApiClient] = None, prefix: Optional[str] = None) -> List[Any]:
        """Returns a list of s3.Object objects for the s3.Bucket

        Args:
            aws_client: The AwsApiClient for the current cluster
            prefix: Prefix to filter objects by
        """
        bucket = self.get_resource(aws_client)
        if bucket is None:
            logger.warning(f"Could not get bucket: {self.name}")
            return []

        logger.debug(f"Getting objects for bucket: {bucket.name}")
        # Get all objects in bucket
        object_summaries = bucket.objects.all()
        all_objects: List[S3Object] = []
        for object_summary in object_summaries:
            if prefix is not None and not object_summary.key.startswith(prefix):
                continue
            all_objects.append(
                S3Object(
                    bucket_name=bucket.name,
                    name=object_summary.key,
                )
            )
        return all_objects
