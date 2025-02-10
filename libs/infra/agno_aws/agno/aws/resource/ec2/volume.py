from typing import Any, Dict, Optional

from typing_extensions import Literal

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.cli.console import print_info
from agno.utils.log import logger


class EbsVolume(AwsResource):
    """
    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#volume
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#EC2.Client.create_volume
    """

    resource_type: Optional[str] = "EbsVolume"
    service_name: str = "ec2"

    # The unique name to give to your volume.
    name: str
    # The size of the volume, in GiBs. You must specify either a snapshot ID or a volume size.
    # If you specify a snapshot, the default is the snapshot size. You can specify a volume size that is
    # equal to or larger than the snapshot size.
    #
    # The following are the supported volumes sizes for each volume type:
    # gp2 and gp3 : 1-16,384
    # io1 and io2 : 4-16,384
    # st1 and sc1 : 125-16,384
    # standard : 1-1,024
    size: int
    # The Availability Zone in which to create the volume.
    availability_zone: str
    # Indicates whether the volume should be encrypted. The effect of setting the encryption state to
    # true depends on the volume origin (new or from a snapshot), starting encryption state, ownership,
    # and whether encryption by default is enabled.
    # Encrypted Amazon EBS volumes must be attached to instances that support Amazon EBS encryption.
    encrypted: Optional[bool] = None
    # The number of I/O operations per second (IOPS). For gp3 , io1 , and io2 volumes, this represents the
    # number of IOPS that are provisioned for the volume. For gp2 volumes, this represents the baseline
    # performance of the volume and the rate at which the volume accumulates I/O credits for bursting.
    #
    # The following are the supported values for each volume type:
    # gp3 : 3,000-16,000 IOPS
    # io1 : 100-64,000 IOPS
    # io2 : 100-64,000 IOPS
    #
    # This parameter is required for io1 and io2 volumes.
    # The default for gp3 volumes is 3,000 IOPS.
    # This parameter is not supported for gp2 , st1 , sc1 , or standard volumes.
    iops: Optional[int] = None
    # The identifier of the Key Management Service (KMS) KMS key to use for Amazon EBS encryption.
    # If this parameter is not specified, your KMS key for Amazon EBS is used. If KmsKeyId is specified,
    # the encrypted state must be true .
    kms_key_id: Optional[str] = None
    # The Amazon Resource Name (ARN) of the Outpost.
    outpost_arn: Optional[str] = None
    # The snapshot from which to create the volume. You must specify either a snapshot ID or a volume size.
    snapshot_id: Optional[str] = None
    # The volume type. This parameter can be one of the following values:
    #
    # General Purpose SSD: gp2 | gp3
    # Provisioned IOPS SSD: io1 | io2
    # Throughput Optimized HDD: st1
    # Cold HDD: sc1
    # Magnetic: standard
    #
    # Default: gp2
    volume_type: Optional[Literal["standard", "io_1", "io_2", "gp_2", "sc_1", "st_1", "gp_3"]] = None
    # Checks whether you have the required permissions for the action, without actually making the request,
    # and provides an error response. If you have the required permissions, the error response is DryRunOperation.
    # Otherwise, it is UnauthorizedOperation .
    dry_run: Optional[bool] = None
    # The tags to apply to the volume during creation.
    tags: Optional[Dict[str, str]] = None
    # The tag to use for volume name
    name_tag: str = "Name"
    # Indicates whether to enable Amazon EBS Multi-Attach. If you enable Multi-Attach, you can attach the volume to
    # up to 16 Instances built on the Nitro System in the same Availability Zone. This parameter is supported with
    # io1 and io2 volumes only.
    multi_attach_enabled: Optional[bool] = None
    # The throughput to provision for a volume, with a maximum of 1,000 MiB/s.
    # This parameter is valid only for gp3 volumes.
    # Valid Range: Minimum value of 125. Maximum value of 1000.
    throughput: Optional[int] = None
    # Unique, case-sensitive identifier that you provide to ensure the idempotency of the request.
    # This field is autopopulated if not provided.
    client_token: Optional[str] = None

    wait_for_create: bool = False

    volume_id: Optional[str] = None

    def _create(self, aws_client: AwsApiClient) -> bool:
        """Creates the EbsVolume

        Args:
            aws_client: The AwsApiClient for the current volume
        """
        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")

        # Step 1: Build Volume configuration
        # Add name as a tag because volumes do not have names
        tags = {self.name_tag: self.name}
        if self.tags is not None and isinstance(self.tags, dict):
            tags.update(self.tags)

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}
        if self.encrypted:
            not_null_args["Encrypted"] = self.encrypted
        if self.iops:
            not_null_args["Iops"] = self.iops
        if self.kms_key_id:
            not_null_args["KmsKeyId"] = self.kms_key_id
        if self.outpost_arn:
            not_null_args["OutpostArn"] = self.outpost_arn
        if self.snapshot_id:
            not_null_args["SnapshotId"] = self.snapshot_id
        if self.volume_type:
            not_null_args["VolumeType"] = self.volume_type
        if self.dry_run:
            not_null_args["DryRun"] = self.dry_run
        if tags:
            not_null_args["TagSpecifications"] = [
                {
                    "ResourceType": "volume",
                    "Tags": [{"Key": k, "Value": v} for k, v in tags.items()],
                },
            ]
        if self.multi_attach_enabled:
            not_null_args["MultiAttachEnabled"] = self.multi_attach_enabled
        if self.throughput:
            not_null_args["Throughput"] = self.throughput
        if self.client_token:
            not_null_args["ClientToken"] = self.client_token

        # Step 2: Create Volume
        service_client = self.get_service_client(aws_client)
        try:
            create_response = service_client.create_volume(
                AvailabilityZone=self.availability_zone,
                Size=self.size,
                **not_null_args,
            )
            logger.debug(f"create_response: {create_response}")

            # Validate Volume creation
            if create_response is not None:
                create_time = create_response.get("CreateTime", None)
                self.volume_id = create_response.get("VolumeId", None)
                logger.debug(f"create_time: {create_time}")
                logger.debug(f"volume_id: {self.volume_id}")
                if create_time is not None:
                    self.active_resource = create_response
                    return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def post_create(self, aws_client: AwsApiClient) -> bool:
        # Wait for Volume to be created
        if self.wait_for_create:
            try:
                if self.volume_id is not None:
                    print_info(f"Waiting for {self.get_resource_type()} to be created.")
                    waiter = self.get_service_client(aws_client).get_waiter("volume_available")
                    waiter.wait(
                        VolumeIds=[self.volume_id],
                        WaiterConfig={
                            "Delay": self.waiter_delay,
                            "MaxAttempts": self.waiter_max_attempts,
                        },
                    )
                else:
                    logger.warning("Skipping waiter, no volume_id found")
            except Exception as e:
                logger.error("Waiter failed.")
                logger.error(e)
        return True

    def _read(self, aws_client: AwsApiClient) -> Optional[Any]:
        """Returns the EbsVolume

        Args:
            aws_client: The AwsApiClient for the current volume
        """
        logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")

        from botocore.exceptions import ClientError

        service_client = self.get_service_client(aws_client)
        try:
            volume = None
            describe_volumes = service_client.describe_volumes(
                Filters=[
                    {
                        "Name": "tag:" + self.name_tag,
                        "Values": [self.name],
                    },
                ],
            )
            # logger.debug(f"describe_volumes: {describe_volumes}")
            for _volume in describe_volumes.get("Volumes", []):
                _volume_tags = _volume.get("Tags", None)
                if _volume_tags is not None and isinstance(_volume_tags, list):
                    for _tag in _volume_tags:
                        if _tag["Key"] == self.name_tag and _tag["Value"] == self.name:
                            volume = _volume
                            break
                # found volume, break loop
                if volume is not None:
                    break

            if volume is not None:
                create_time = volume.get("CreateTime", None)
                logger.debug(f"create_time: {create_time}")
                self.volume_id = volume.get("VolumeId", None)
                logger.debug(f"volume_id: {self.volume_id}")
                self.active_resource = volume
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return self.active_resource

    def _delete(self, aws_client: AwsApiClient) -> bool:
        """Deletes the EbsVolume

        Args:
            aws_client: The AwsApiClient for the current volume
        """
        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")

        self.active_resource = None
        service_client = self.get_service_client(aws_client)
        try:
            volume = self._read(aws_client)
            logger.debug(f"EbsVolume: {volume}")
            if volume is None or self.volume_id is None:
                logger.warning(f"No {self.get_resource_type()} to delete")
                return True

            # detach the volume from all instances
            for attachment in volume.get("Attachments", []):
                device = attachment.get("Device", None)
                instance_id = attachment.get("InstanceId", None)
                print_info(f"Detaching volume from device: {device}, instance_id: {instance_id}")
                service_client.detach_volume(
                    Device=device,
                    InstanceId=instance_id,
                    VolumeId=self.volume_id,
                )

            # delete volume
            service_client.delete_volume(VolumeId=self.volume_id)
            return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be deleted.")
            logger.error("Please try again or delete resources manually.")
            logger.error(e)
        return False

    def _update(self, aws_client: AwsApiClient) -> bool:
        """Updates the EbsVolume

        Args:
            aws_client: The AwsApiClient for the current volume
        """
        print_info(f"Updating {self.get_resource_type()}: {self.get_resource_name()}")

        # Step 1: Build Volume configuration
        # Add name as a tag because volumes do not have names
        tags = {self.name_tag: self.name}
        if self.tags is not None and isinstance(self.tags, dict):
            tags.update(self.tags)

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}
        if self.iops:
            not_null_args["Iops"] = self.iops
        if self.volume_type:
            not_null_args["VolumeType"] = self.volume_type
        if self.dry_run:
            not_null_args["DryRun"] = self.dry_run
        if tags:
            not_null_args["TagSpecifications"] = [
                {
                    "ResourceType": "volume",
                    "Tags": [{"Key": k, "Value": v} for k, v in tags.items()],
                },
            ]
        if self.multi_attach_enabled:
            not_null_args["MultiAttachEnabled"] = self.multi_attach_enabled
        if self.throughput:
            not_null_args["Throughput"] = self.throughput

        service_client = self.get_service_client(aws_client)
        try:
            volume = self._read(aws_client)
            logger.debug(f"EbsVolume: {volume}")
            if volume is None or self.volume_id is None:
                logger.warning(f"No {self.get_resource_type()} to update")
                return True

            # update volume
            update_response = service_client.modify_volume(
                VolumeId=self.volume_id,
                **not_null_args,
            )
            logger.debug(f"update_response: {update_response}")

            # Validate Volume update
            volume_modification = update_response.get("VolumeModification", None)
            if volume_modification is not None:
                volume_id_after_modification = volume_modification.get("VolumeId", None)
                logger.debug(f"volume_id: {volume_id_after_modification}")
                if volume_id_after_modification is not None:
                    return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be updated.")
            logger.error("Please try again or update resources manually.")
            logger.error(e)
        return False

    def get_volume_id(self, aws_client: Optional[AwsApiClient] = None) -> Optional[str]:
        """Returns the volume_id of the EbsVolume"""

        client = aws_client or self.get_aws_client()
        if client is not None:
            self._read(client)
        return self.volume_id
