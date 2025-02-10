from typing import Any, Dict, List, Optional, Union

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.aws.resource.cloudformation.stack import CloudFormationStack
from agno.aws.resource.reference import AwsReference
from agno.cli.console import print_info
from agno.utils.log import logger


class CacheSubnetGroup(AwsResource):
    """
    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/elasticache.html#ElastiCache.Client.create_cache_subnet_group

    Creates a cache subnet group.
    """

    resource_type: Optional[str] = "CacheSubnetGroup"
    service_name: str = "elasticache"

    # A name for the cache subnet group. This value is stored as a lowercase string.
    # Constraints: Must contain no more than 255 alphanumeric characters or hyphens.
    name: str
    # A description for the cache subnet group.
    description: Optional[str] = None
    # A list of VPC subnet IDs for the cache subnet group.
    subnet_ids: Optional[Union[List[str], AwsReference]] = None
    # Get Subnet IDs from a VPC CloudFormationStack
    # First gets private subnets from the vpc stack, then public subnets
    vpc_stack: Optional[CloudFormationStack] = None
    # A list of tags to be added to this resource.
    tags: Optional[List[Dict[str, str]]] = None

    def get_subnet_ids(self, aws_client: AwsApiClient) -> List[str]:
        """Returns the subnet_ids for the CacheSubnetGroup

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        subnet_ids = []
        if self.subnet_ids is not None:
            if isinstance(self.subnet_ids, list):
                logger.debug("Getting subnet_ids from list")
                subnet_ids = self.subnet_ids
            elif isinstance(self.subnet_ids, AwsReference):
                logger.debug("Getting subnet_ids from reference")
                subnet_ids = self.subnet_ids.get_reference(aws_client=aws_client)
        if len(subnet_ids) == 0 and self.vpc_stack is not None:
            logger.debug("Getting private subnet_ids from vpc stack")
            private_subnet_ids = self.vpc_stack.get_private_subnets(aws_client=aws_client)
            if private_subnet_ids is not None:
                subnet_ids.extend(private_subnet_ids)
            if len(subnet_ids) == 0:
                logger.debug("Getting public subnet_ids from vpc stack")
                public_subnet_ids = self.vpc_stack.get_public_subnets(aws_client=aws_client)
                if public_subnet_ids is not None:
                    subnet_ids.extend(public_subnet_ids)
        return subnet_ids

    def _create(self, aws_client: AwsApiClient) -> bool:
        """Creates the CacheSubnetGroup

        Args:
            aws_client: The AwsApiClient for the current cluster
        """

        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")
        try:
            # Get subnet_ids
            subnet_ids = self.get_subnet_ids(aws_client=aws_client)

            # create a dict of args which are not null, otherwise aws type validation fails
            not_null_args: Dict[str, Any] = {}
            if self.tags:
                not_null_args["Tags"] = self.tags

            # Create CacheSubnetGroup
            service_client = self.get_service_client(aws_client)
            create_response = service_client.create_cache_subnet_group(
                CacheSubnetGroupName=self.name,
                CacheSubnetGroupDescription=self.description or f"Created for {self.name}",
                SubnetIds=subnet_ids,
                **not_null_args,
            )
            logger.debug(f"create_response type: {type(create_response)}")
            logger.debug(f"create_response: {create_response}")

            self.active_resource = create_response.get("CacheSubnetGroup", None)
            if self.active_resource is not None:
                print_info(f"{self.get_resource_type()}: {self.get_resource_name()} created")
                logger.debug(f"CacheSubnetGroup: {self.active_resource}")
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def _read(self, aws_client: AwsApiClient) -> Optional[Any]:
        """Returns the CacheSubnetGroup

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        from botocore.exceptions import ClientError

        logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")
        try:
            service_client = self.get_service_client(aws_client)
            describe_response = service_client.describe_cache_subnet_groups(CacheSubnetGroupName=self.name)
            logger.debug(f"describe_response type: {type(describe_response)}")
            logger.debug(f"describe_response: {describe_response}")

            cache_subnet_group_list = describe_response.get("CacheSubnetGroups", None)
            if cache_subnet_group_list is not None and isinstance(cache_subnet_group_list, list):
                for _cache_subnet_group in cache_subnet_group_list:
                    _cache_sg_name = _cache_subnet_group.get("CacheSubnetGroupName", None)
                    if _cache_sg_name == self.name:
                        self.active_resource = _cache_subnet_group
                        break

            if self.active_resource is None:
                logger.debug(f"No {self.get_resource_type()} found")
                return None

            logger.debug(f"CacheSubnetGroup: {self.active_resource}")
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return self.active_resource

    def _delete(self, aws_client: AwsApiClient) -> bool:
        """Deletes the CacheSubnetGroup

        Args:
            aws_client: The AwsApiClient for the current cluster
        """

        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")
        try:
            service_client = self.get_service_client(aws_client)
            self.active_resource = None

            delete_response = service_client.delete_cache_subnet_group(CacheSubnetGroupName=self.name)
            logger.debug(f"delete_response: {delete_response}")
            return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be deleted.")
            logger.error("Please try again or delete resources manually.")
            logger.error(e)
        return False

    def _update(self, aws_client: AwsApiClient) -> bool:
        """Updates the CacheSubnetGroup

        Args:
            aws_client: The AwsApiClient for the current cluster
        """

        print_info(f"Updating {self.get_resource_type()}: {self.get_resource_name()}")
        try:
            # Get subnet_ids
            subnet_ids = self.get_subnet_ids(aws_client=aws_client)

            # Update CacheSubnetGroup
            service_client = self.get_service_client(aws_client)
            update_response = service_client.modify_cache_subnet_group(
                CacheSubnetGroupName=self.name,
                CacheSubnetGroupDescription=self.description or f"Created for {self.name}",
                SubnetIds=subnet_ids,
            )
            logger.debug(f"update_response: {update_response}")

            self.active_resource = update_response.get("CacheSubnetGroup", None)
            if self.active_resource is not None:
                print_info(f"{self.get_resource_type()}: {self.get_resource_name()} updated")
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be updated.")
            logger.error(e)
        return False
