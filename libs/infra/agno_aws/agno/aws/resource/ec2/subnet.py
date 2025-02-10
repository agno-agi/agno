from typing import List, Optional

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.utils.log import logger


class Subnet(AwsResource):
    """
    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html#subnet
    """

    name: str
    resource_type: Optional[str] = "Subnet"
    service_name: str = "ec2"

    def get_availability_zone(self, aws_client: Optional[AwsApiClient] = None) -> Optional[str]:
        # logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")

        from botocore.exceptions import ClientError

        client: AwsApiClient = aws_client or self.get_aws_client()
        service_resource = self.get_service_resource(client)
        try:
            subnet = service_resource.Subnet(self.name)
            az = subnet.availability_zone
            logger.debug(f"AZ for {self.name}: {az}")
            return az
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}: {e}")
        return None

    def get_vpc_id(self, aws_client: Optional[AwsApiClient] = None) -> Optional[str]:
        # logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")

        from botocore.exceptions import ClientError

        client: AwsApiClient = aws_client or self.get_aws_client()
        service_resource = self.get_service_resource(client)
        try:
            subnet = service_resource.Subnet(self.name)
            vpc_id = subnet.vpc_id
            logger.debug(f"VPC ID for {self.name}: {vpc_id}")
            return vpc_id
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}: {e}")
        return None


def get_vpc_id_from_subnet_ids(
    subnet_ids: Optional[List[str]], aws_client: Optional[AwsApiClient] = None
) -> Optional[str]:
    if subnet_ids is None:
        return None

    # Get VPC ID from subnets
    vpc_ids = set()
    for subnet in subnet_ids:
        _vpc = Subnet(name=subnet).get_vpc_id(aws_client)
        vpc_ids.add(_vpc)
    if len(vpc_ids) > 1:
        raise ValueError("Subnets must be in the same VPC")
    vpc_id = vpc_ids.pop() if len(vpc_ids) == 1 else None
    return vpc_id
