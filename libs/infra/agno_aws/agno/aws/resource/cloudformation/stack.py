from typing import Any, List, Optional

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.cli.console import print_info
from agno.utils.log import logger


class CloudFormationStack(AwsResource):
    """
    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudformation.html#service-resource
    """

    resource_type: Optional[str] = "CloudFormationStack"
    service_name: str = "cloudformation"

    # StackName: The name must be unique in the Region in which you are creating the stack.
    name: str
    # Location of file containing the template body.
    # The URL must point to a template (max size: 460,800 bytes) that's located in an
    # Amazon S3 bucket or a Systems Manager document.
    template_url: str
    # parameters: Optional[List[Dict[str, Union[str, bool]]]] = None
    # disable_rollback: Optional[bool] = None

    def _create(self, aws_client: AwsApiClient) -> bool:
        """Creates the CloudFormationStack

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")

        # Step 1: Create CloudFormationStack
        service_resource = self.get_service_resource(aws_client)
        try:
            stack = service_resource.create_stack(
                StackName=self.name,
                TemplateURL=self.template_url,
            )
            logger.debug(f"Stack: {stack}")

            # Validate Stack creation
            stack.load()
            creation_time = stack.creation_time
            logger.debug(f"creation_time: {creation_time}")
            if creation_time is not None:
                self.active_resource = stack
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def post_create(self, aws_client: AwsApiClient) -> bool:
        # Wait for Stack to be created
        if self.wait_for_create:
            try:
                print_info(f"Waiting for {self.get_resource_type()} to be created.")
                waiter = self.get_service_client(aws_client).get_waiter("stack_create_complete")
                waiter.wait(
                    StackName=self.name,
                    WaiterConfig={
                        "Delay": self.waiter_delay,
                        "MaxAttempts": self.waiter_max_attempts,
                    },
                )
            except Exception as e:
                logger.error("Waiter failed.")
                logger.error(e)
                return False
        return True

    def _read(self, aws_client: AwsApiClient) -> Optional[Any]:
        """Returns the CloudFormationStack

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")

        from botocore.exceptions import ClientError

        service_resource = self.get_service_resource(aws_client)
        try:
            stack = service_resource.Stack(name=self.name)

            stack.load()
            creation_time = stack.creation_time
            logger.debug(f"creation_time: {creation_time}")
            if creation_time is not None:
                logger.debug(f"Stack found: {stack.stack_name}")
                self.active_resource = stack
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return self.active_resource

    def _delete(self, aws_client: AwsApiClient) -> bool:
        """Deletes the CloudFormationStack

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")

        self.active_resource = None
        try:
            stack = self._read(aws_client)
            logger.debug(f"Stack: {stack}")
            if stack is None:
                logger.warning(f"No {self.get_resource_type()} to delete")
                return True

            stack.delete()
            # print_info("Stack deleted")
            return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be deleted.")
            logger.error("Please try again or delete resources manually.")
            logger.error(e)
        return False

    def post_delete(self, aws_client: AwsApiClient) -> bool:
        # Wait for Stack to be deleted
        if self.wait_for_delete:
            try:
                print_info(f"Waiting for {self.get_resource_type()} to be deleted.")
                waiter = self.get_service_client(aws_client).get_waiter("stack_delete_complete")
                waiter.wait(
                    StackName=self.name,
                    WaiterConfig={
                        "Delay": self.waiter_delay,
                        "MaxAttempts": self.waiter_max_attempts,
                    },
                )
                return True
            except Exception as e:
                logger.error("Waiter failed.")
                logger.error(e)
        return True

    def get_stack_resource(self, aws_client: AwsApiClient, logical_id: str) -> Optional[Any]:
        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudformation.html#CloudFormation.StackResource
        # logger.debug(f"Getting StackResource {logical_id} for {self.name}")
        try:
            service_resource = self.get_service_resource(aws_client)
            stack_resource = service_resource.StackResource(self.name, logical_id)
            return stack_resource
        except Exception as e:
            logger.error(e)
        return None

    def get_stack_resource_physical_id(self, stack_resource: Any) -> Optional[str]:
        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/cloudformation.html#CloudFormation.StackResource
        try:
            physical_resource_id = stack_resource.physical_resource_id if stack_resource is not None else None
            logger.debug(f"{stack_resource.logical_id}: {physical_resource_id}")
            return physical_resource_id
        except Exception:
            return None

    def get_private_subnets(self, aws_client: Optional[AwsApiClient] = None) -> Optional[List[str]]:
        try:
            client: AwsApiClient = (
                aws_client
                if aws_client is not None
                else AwsApiClient(aws_region=self.get_aws_region(), aws_profile=self.get_aws_profile())
            )

            private_subnets = []

            private_subnet_1_stack_resource = self.get_stack_resource(client, "PrivateSubnet01")
            private_subnet_1_physical_resource_id = self.get_stack_resource_physical_id(private_subnet_1_stack_resource)
            if private_subnet_1_physical_resource_id is not None:
                private_subnets.append(private_subnet_1_physical_resource_id)

            private_subnet_2_stack_resource = self.get_stack_resource(client, "PrivateSubnet02")
            private_subnet_2_physical_resource_id = self.get_stack_resource_physical_id(private_subnet_2_stack_resource)
            if private_subnet_2_physical_resource_id is not None:
                private_subnets.append(private_subnet_2_physical_resource_id)

            private_subnet_3_stack_resource = self.get_stack_resource(client, "PrivateSubnet03")
            private_subnet_3_physical_resource_id = self.get_stack_resource_physical_id(private_subnet_3_stack_resource)
            if private_subnet_3_physical_resource_id is not None:
                private_subnets.append(private_subnet_3_physical_resource_id)

            return private_subnets if (len(private_subnets) > 0) else None
        except Exception as e:
            logger.error(e)
        return None

    def get_public_subnets(self, aws_client: Optional[AwsApiClient] = None) -> Optional[List[str]]:
        try:
            client: AwsApiClient = (
                aws_client
                if aws_client is not None
                else AwsApiClient(aws_region=self.get_aws_region(), aws_profile=self.get_aws_profile())
            )

            public_subnets = []

            public_subnet_1_stack_resource = self.get_stack_resource(client, "PublicSubnet01")
            public_subnet_1_physical_resource_id = self.get_stack_resource_physical_id(public_subnet_1_stack_resource)
            if public_subnet_1_physical_resource_id is not None:
                public_subnets.append(public_subnet_1_physical_resource_id)

            public_subnet_2_stack_resource = self.get_stack_resource(client, "PublicSubnet02")
            public_subnet_2_physical_resource_id = self.get_stack_resource_physical_id(public_subnet_2_stack_resource)
            if public_subnet_2_physical_resource_id is not None:
                public_subnets.append(public_subnet_2_physical_resource_id)

            return public_subnets if (len(public_subnets) > 0) else None
        except Exception as e:
            logger.error(e)
        return None

    def get_security_group(self, aws_client: Optional[AwsApiClient] = None) -> Optional[str]:
        try:
            client: AwsApiClient = (
                aws_client
                if aws_client is not None
                else AwsApiClient(aws_region=self.get_aws_region(), aws_profile=self.get_aws_profile())
            )

            security_group_stack_resource = self.get_stack_resource(client, "ControlPlaneSecurityGroup")
            security_group_physical_resource_id = (
                security_group_stack_resource.physical_resource_id
                if security_group_stack_resource is not None
                else None
            )
            logger.debug(f"security_group: {security_group_physical_resource_id}")

            return security_group_physical_resource_id
        except Exception as e:
            logger.error(e)
        return None
