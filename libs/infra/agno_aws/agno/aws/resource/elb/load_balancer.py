from typing import Any, Dict, List, Optional, Union

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.aws.resource.ec2.security_group import SecurityGroup
from agno.aws.resource.ec2.subnet import Subnet
from agno.cli.console import print_info
from agno.utils.log import logger


class LoadBalancer(AwsResource):
    """
    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/elbv2.html
    """

    resource_type: Optional[str] = "LoadBalancer"
    service_name: str = "elbv2"

    # Name of the Load Balancer.
    name: str
    subnets: Optional[List[Union[str, Subnet]]] = None
    subnet_mappings: Optional[List[Dict[str, str]]] = None
    security_groups: Optional[List[Union[str, SecurityGroup]]] = None
    scheme: Optional[str] = None
    tags: Optional[List[Dict[str, str]]] = None
    type: Optional[str] = None
    ip_address_type: Optional[str] = None
    customer_owned_ipv_4_pool: Optional[str] = None

    # Protocol for load_balancer: HTTP or HTTPS
    protocol: str = "HTTP"

    def _create(self, aws_client: AwsApiClient) -> bool:
        """Creates the Load Balancer

        Args:
            aws_client: The AwsApiClient for the current Load Balancer
        """
        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}

        if self.subnets is not None:
            subnet_ids = []
            for subnet in self.subnets:
                if isinstance(subnet, Subnet):
                    subnet_ids.append(subnet.name)
                elif isinstance(subnet, str):
                    subnet_ids.append(subnet)
            not_null_args["Subnets"] = subnet_ids

        if self.subnet_mappings is not None:
            not_null_args["SubnetMappings"] = self.subnet_mappings

        if self.security_groups is not None:
            security_group_ids = []
            for sg in self.security_groups:
                if isinstance(sg, SecurityGroup):
                    security_group_ids.append(sg.get_security_group_id(aws_client))
                else:
                    security_group_ids.append(sg)
            not_null_args["SecurityGroups"] = security_group_ids

        if self.scheme is not None:
            not_null_args["Scheme"] = self.scheme
        if self.tags is not None:
            not_null_args["tags"] = self.tags
        if self.type is not None:
            not_null_args["Type"] = self.type
        if self.ip_address_type is not None:
            not_null_args["IpAddressType"] = self.ip_address_type
        if self.customer_owned_ipv_4_pool is not None:
            not_null_args["CustomerOwnedIpv4Pool"] = self.customer_owned_ipv_4_pool

        # Create LoadBalancer
        service_client = self.get_service_client(aws_client)
        try:
            create_response = service_client.create_load_balancer(
                Name=self.name,
                **not_null_args,
            )
            logger.debug(f"Create Response: {create_response}")
            resource_dict = create_response.get("LoadBalancers", {})

            # Validate resource creation
            if resource_dict is not None:
                self.active_resource = create_response
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def post_create(self, aws_client: AwsApiClient) -> bool:
        # Wait for LoadBalancer to be created
        if self.wait_for_create:
            try:
                print_info(f"Waiting for {self.get_resource_type()} to be created.")
                waiter = self.get_service_client(aws_client).get_waiter("load_balancer_exists")
                waiter.wait(
                    Names=[self.get_resource_name()],
                    WaiterConfig={
                        "Delay": self.waiter_delay,
                        "MaxAttempts": self.waiter_max_attempts,
                    },
                )
            except Exception as e:
                logger.error("Waiter failed.")
                logger.error(e)
        # Read the LoadBalancer
        elb = self._read(aws_client)
        if elb is None:
            logger.error(f"Error reading {self.get_resource_type()}. Please get DNS name manually.")
        else:
            dns_name = elb.get("DNSName", None)
            print_info(f"LoadBalancer DNS: {self.protocol.lower()}://{dns_name}")
        return True

    def _read(self, aws_client: AwsApiClient) -> Optional[Any]:
        """Returns the LoadBalancer

        Args:
            aws_client: The AwsApiClient for the current LoadBalancer
        """
        logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")

        from botocore.exceptions import ClientError

        service_client = self.get_service_client(aws_client)
        try:
            describe_response = service_client.describe_load_balancers(Names=[self.name])
            logger.debug(f"Describe Response: {describe_response}")
            resource_list = describe_response.get("LoadBalancers", None)

            if resource_list is not None and isinstance(resource_list, list):
                self.active_resource = resource_list[0]
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return self.active_resource

    def _delete(self, aws_client: AwsApiClient) -> bool:
        """Deletes the LoadBalancer

        Args:
            aws_client: The AwsApiClient for the current LoadBalancer
        """
        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")

        service_client = self.get_service_client(aws_client)
        self.active_resource = None

        try:
            lb_arn = self.get_arn(aws_client)
            if lb_arn is None:
                logger.warning(f"{self.get_resource_type()} not found.")
                return True
            delete_response = service_client.delete_load_balancer(LoadBalancerArn=lb_arn)
            logger.debug(f"Delete Response: {delete_response}")
            return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be deleted.")
            logger.error("Please try again or delete resources manually.")
            logger.error(e)
        return False

    def post_delete(self, aws_client: AwsApiClient) -> bool:
        # Wait for LoadBalancer to be deleted
        if self.wait_for_delete:
            try:
                print_info(f"Waiting for {self.get_resource_type()} to be deleted.")
                waiter = self.get_service_client(aws_client).get_waiter("load_balancers_deleted")
                waiter.wait(
                    Names=[self.get_resource_name()],
                    WaiterConfig={
                        "Delay": self.waiter_delay,
                        "MaxAttempts": self.waiter_max_attempts,
                    },
                )
            except Exception as e:
                logger.error("Waiter failed.")
                logger.error(e)
        return True

    def get_arn(self, aws_client: AwsApiClient) -> Optional[str]:
        lb = self._read(aws_client)
        if lb is None:
            return None
        lb_arn = lb.get("LoadBalancerArn", None)
        return lb_arn
