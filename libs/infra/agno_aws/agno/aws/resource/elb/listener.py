from typing import Any, Dict, List, Optional

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.acm.certificate import AcmCertificate
from agno.aws.resource.base import AwsResource
from agno.aws.resource.elb.load_balancer import LoadBalancer
from agno.aws.resource.elb.target_group import TargetGroup
from agno.cli.console import print_info
from agno.utils.log import logger


class Listener(AwsResource):
    """
    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/elbv2/client/create_listener.html
    """

    resource_type: Optional[str] = "Listener"
    service_name: str = "elbv2"

    # Name of the Listener
    name: str
    load_balancer: Optional[LoadBalancer] = None
    target_group: Optional[TargetGroup] = None
    load_balancer_arn: Optional[str] = None
    protocol: Optional[str] = None
    port: Optional[int] = None
    ssl_policy: Optional[str] = None
    certificates: Optional[List[Dict[str, Any]]] = None
    acm_certificates: Optional[List[AcmCertificate]] = None
    default_actions: Optional[List[Dict]] = None
    alpn_policy: Optional[List[str]] = None
    tags: Optional[List[Dict[str, str]]] = None

    def _create(self, aws_client: AwsApiClient) -> bool:
        """Creates the Listener

        Args:
            aws_client: The AwsApiClient for the current Listener
        """
        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")

        load_balancer_arn = self.get_load_balancer_arn(aws_client)
        if load_balancer_arn is None:
            logger.error("Load balancer ARN not available")
            return False

        listener_port = self.get_listener_port()
        listener_protocol = self.get_listener_protocol()
        listener_certificates = self.get_listener_certificates(aws_client)

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}
        if listener_port is not None:
            not_null_args["Port"] = listener_port
        if listener_protocol is not None:
            not_null_args["Protocol"] = listener_protocol
        if listener_certificates is not None:
            not_null_args["Certificates"] = listener_certificates
        if self.ssl_policy is not None:
            not_null_args["SslPolicy"] = self.ssl_policy
        if self.alpn_policy is not None:
            not_null_args["AlpnPolicy"] = self.alpn_policy

        # listener tags container a name for the listener
        listener_tags = self.get_listener_tags()
        if listener_tags is not None:
            not_null_args["Tags"] = listener_tags

        if self.default_actions is not None:
            not_null_args["DefaultActions"] = self.default_actions
        elif self.target_group is not None:
            target_group_arn = self.target_group.get_arn(aws_client)
            if target_group_arn is None:
                logger.error("Target group ARN not available")
                return False
            not_null_args["DefaultActions"] = [{"Type": "forward", "TargetGroupArn": target_group_arn}]
        else:
            logger.warning(f"Neither target group nor default actions provided for {self.get_resource_name()}")
            return True

        # Create Listener
        service_client = self.get_service_client(aws_client)
        try:
            create_response = service_client.create_listener(
                LoadBalancerArn=load_balancer_arn,
                **not_null_args,
            )
            logger.debug(f"Create Response: {create_response}")
            resource_dict = create_response.get("Listeners", {})

            # Validate resource creation
            if resource_dict is not None:
                self.active_resource = create_response
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def _read(self, aws_client: AwsApiClient) -> Optional[Any]:
        """Returns the Listener

        Args:
            aws_client: The AwsApiClient for the current Listener
        """
        logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")

        from botocore.exceptions import ClientError

        service_client = self.get_service_client(aws_client)
        try:
            load_balancer_arn = self.get_load_balancer_arn(aws_client)
            if load_balancer_arn is None:
                # logger.error(f"Load balancer ARN not available")
                return None

            describe_response = service_client.describe_listeners(LoadBalancerArn=load_balancer_arn)
            logger.debug(f"Describe Response: {describe_response}")
            resource_list = describe_response.get("Listeners", None)

            if resource_list is not None and isinstance(resource_list, list):
                # We identify the current listener by the port and protocol
                current_listener_port = self.get_listener_port()
                current_listener_protocol = self.get_listener_protocol()
                for resource in resource_list:
                    if (
                        resource.get("Port", None) == current_listener_port
                        and resource.get("Protocol", None) == current_listener_protocol
                    ):
                        logger.debug(f"Found {self.get_resource_type()}: {self.get_resource_name()}")
                        self.active_resource = resource
                        break
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return self.active_resource

    def _delete(self, aws_client: AwsApiClient) -> bool:
        """Deletes the Listener

        Args:
            aws_client: The AwsApiClient for the current Listener
        """
        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")

        service_client = self.get_service_client(aws_client)
        self.active_resource = None

        try:
            listener_arn = self.get_arn(aws_client)
            if listener_arn is None:
                logger.error(f"Listener {self.get_resource_name()} not found.")
                return True

            delete_response = service_client.delete_listener(ListenerArn=listener_arn)
            logger.debug(f"Delete Response: {delete_response}")
            return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be deleted.")
            logger.error("Please try again or delete resources manually.")
            logger.error(e)
        return False

    def _update(self, aws_client: AwsApiClient) -> bool:
        """Update EcsService"""
        print_info(f"Updating {self.get_resource_type()}: {self.get_resource_name()}")

        listener_arn = self.get_arn(aws_client)
        if listener_arn is None:
            logger.error(f"Listener {self.get_resource_name()} not found.")
            return True

        listener_port = self.get_listener_port()
        listener_protocol = self.get_listener_protocol()
        listener_certificates = self.get_listener_certificates(aws_client)

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}
        if listener_port is not None:
            not_null_args["Port"] = listener_port
        if listener_protocol is not None:
            not_null_args["Protocol"] = listener_protocol
        if listener_certificates is not None:
            not_null_args["Certificates"] = listener_certificates
        if self.ssl_policy is not None:
            not_null_args["SslPolicy"] = self.ssl_policy
        if self.alpn_policy is not None:
            not_null_args["AlpnPolicy"] = self.alpn_policy

        if self.default_actions is not None:
            not_null_args["DefaultActions"] = self.default_actions
        elif self.target_group is not None:
            target_group_arn = self.target_group.get_arn(aws_client)
            if target_group_arn is None:
                logger.error("Target group ARN not available")
                return False
            not_null_args["DefaultActions"] = [{"Type": "forward", "TargetGroupArn": target_group_arn}]
        else:
            logger.warning(f"Neither target group nor default actions provided for {self.get_resource_name()}")
            return True

        service_client = self.get_service_client(aws_client)
        try:
            create_response = service_client.modify_listener(
                ListenerArn=listener_arn,
                **not_null_args,
            )
            logger.debug(f"Update Response: {create_response}")
            resource_dict = create_response.get("Listeners", {})

            # Validate resource creation
            if resource_dict is not None:
                print_info(f"Listener updated: {self.get_resource_name()}")
                self.active_resource = create_response
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def get_arn(self, aws_client: AwsApiClient) -> Optional[str]:
        listener = self._read(aws_client)
        if listener is None:
            return None

        listener_arn = listener.get("ListenerArn", None)
        return listener_arn

    def get_load_balancer_arn(self, aws_client: AwsApiClient):
        load_balancer_arn = self.load_balancer_arn
        if load_balancer_arn is None and self.load_balancer:
            load_balancer_arn = self.load_balancer.get_arn(aws_client)

        return load_balancer_arn

    def get_listener_port(self):
        listener_port = self.port
        if listener_port is None and self.load_balancer:
            lb_protocol = self.load_balancer.protocol
            listener_port = 443 if lb_protocol == "HTTPS" else 80

        return listener_port

    def get_listener_protocol(self):
        listener_protocol = self.protocol
        if listener_protocol is None and self.load_balancer:
            listener_protocol = self.load_balancer.protocol

        return listener_protocol

    def get_listener_certificates(self, aws_client: AwsApiClient):
        listener_protocol = self.protocol
        if listener_protocol is None and self.load_balancer:
            listener_protocol = self.load_balancer.protocol

        certificates = self.certificates
        if certificates is None and self.acm_certificates is not None and len(self.acm_certificates) > 0:
            certificates = []
            for cert in self.acm_certificates:
                certificates.append({"CertificateArn": cert.get_certificate_arn(aws_client)})

        return certificates

    def get_listener_tags(self):
        tags = self.tags
        if tags is None:
            tags = []
        tags.append({"Key": "Name", "Value": self.get_resource_name()})

        return tags
