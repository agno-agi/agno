from typing import Any, Dict, List, Optional

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.cli.console import print_info
from agno.utils.log import logger


class EcsCluster(AwsResource):
    """
    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs.html
    """

    resource_type: Optional[str] = "EcsCluster"
    service_name: str = "ecs"

    # Name of the cluster.
    name: str
    # Name for the cluster.
    # Use name if not provided.
    ecs_cluster_name: Optional[str] = None

    tags: Optional[List[Dict[str, str]]] = None
    # The setting to use when creating a cluster.
    settings: Optional[List[Dict[str, Any]]] = None
    # The execute command configuration for the cluster.
    configuration: Optional[Dict[str, Any]] = None
    # The short name of one or more capacity providers to associate with the cluster.
    # A capacity provider must be associated with a cluster before it can be included as part of the default capacity
    # provider strategy of the cluster or used in a capacity provider strategy when calling the CreateService/RunTask.
    capacity_providers: Optional[List[str]] = None
    # The capacity provider strategy to set as the default for the cluster. After a default capacity provider strategy
    # is set for a cluster, when you call the RunTask or CreateService APIs with no capacity provider strategy or
    # launch type specified, the default capacity provider strategy for the cluster is used.
    default_capacity_provider_strategy: Optional[List[Dict[str, Any]]] = None
    # Use this parameter to set a default Service Connect namespace.
    # After you set a default Service Connect namespace, any new services with Service Connect turned on that are
    # created in the cluster are added as client services in the namespace.
    service_connect_namespace: Optional[str] = None

    def get_ecs_cluster_name(self):
        return self.ecs_cluster_name or self.name

    def _create(self, aws_client: AwsApiClient) -> bool:
        """Creates the EcsCluster

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}
        if self.tags is not None:
            not_null_args["tags"] = self.tags
        if self.settings is not None:
            not_null_args["settings"] = self.settings
        if self.configuration is not None:
            not_null_args["configuration"] = self.configuration
        if self.capacity_providers is not None:
            not_null_args["capacityProviders"] = self.capacity_providers
        if self.default_capacity_provider_strategy is not None:
            not_null_args["defaultCapacityProviderStrategy"] = self.default_capacity_provider_strategy
        if self.service_connect_namespace is not None:
            not_null_args["serviceConnectDefaults"] = {
                "namespace": self.service_connect_namespace,
            }

        # Create EcsCluster
        service_client = self.get_service_client(aws_client)
        try:
            create_response = service_client.create_cluster(
                clusterName=self.get_ecs_cluster_name(),
                **not_null_args,
            )
            logger.debug(f"EcsCluster: {create_response}")
            resource_dict = create_response.get("cluster", {})

            # Validate resource creation
            if resource_dict is not None:
                self.active_resource = create_response
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def _read(self, aws_client: AwsApiClient) -> Optional[Any]:
        """Returns the EcsCluster

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")

        from botocore.exceptions import ClientError

        service_client = self.get_service_client(aws_client)
        try:
            cluster_name = self.get_ecs_cluster_name()
            describe_response = service_client.describe_clusters(clusters=[cluster_name])
            logger.debug(f"EcsCluster: {describe_response}")
            resource_list = describe_response.get("clusters", None)

            if resource_list is not None and isinstance(resource_list, list):
                for resource in resource_list:
                    _cluster_identifier = resource.get("clusterName", None)
                    if _cluster_identifier == cluster_name:
                        _cluster_status = resource.get("status", None)
                        if _cluster_status == "ACTIVE":
                            self.active_resource = resource
                            break
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return self.active_resource

    def _delete(self, aws_client: AwsApiClient) -> bool:
        """Deletes the EcsCluster

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")

        service_client = self.get_service_client(aws_client)
        self.active_resource = None

        try:
            delete_response = service_client.delete_cluster(cluster=self.get_ecs_cluster_name())
            logger.debug(f"EcsCluster: {delete_response}")
            return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be deleted.")
            logger.error("Please try again or delete resources manually.")
            logger.error(e)
        return False

    def get_arn(self, aws_client: AwsApiClient) -> Optional[str]:
        tg = self._read(aws_client)
        if tg is None:
            return None
        tg_arn = tg.get("ListenerArn", None)
        return tg_arn
