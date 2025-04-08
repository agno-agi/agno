from pathlib import Path
from typing import Any, Dict, List, Optional

from typing_extensions import Literal

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.aws.resource.ec2.security_group import SecurityGroup
from agno.aws.resource.elasticache.subnet_group import CacheSubnetGroup
from agno.cli.console import print_info
from agno.utils.log import logger


class CacheCluster(AwsResource):
    """
    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/elasticache.html
    """

    resource_type: Optional[str] = "CacheCluster"
    service_name: str = "elasticache"

    # Name of the cluster.
    name: str
    # The node group (shard) identifier. This parameter is stored as a lowercase string.
    # If None, use the name as the cache_cluster_id
    # Constraints:
    #   A name must contain from 1 to 50 alphanumeric characters or hyphens.
    #   The first character must be a letter.
    #   A name cannot end with a hyphen or contain two consecutive hyphens.
    cache_cluster_id: Optional[str] = None
    # The name of the cache engine to be used for this cluster.
    engine: Literal["memcached", "redis"]

    # Compute and memory capacity of the nodes in the node group (shard).
    cache_node_type: str
    # The initial number of cache nodes that the cluster has.
    # For clusters running Redis, this value must be 1.
    # For clusters running Memcached, this value must be between 1 and 40.
    num_cache_nodes: int

    # The ID of the replication group to which this cluster should belong.
    # If this parameter is specified, the cluster is added to the specified replication group as a read replica;
    # otherwise, the cluster is a standalone primary that is not part of any replication group.
    replication_group_id: Optional[str] = None
    # Specifies whether the nodes in this Memcached cluster are created in a single Availability Zone or
    # created across multiple Availability Zones in the cluster's region.
    # This parameter is only supported for Memcached clusters.
    az_mode: Optional[Literal["single-az", "cross-az"]] = None
    # The EC2 Availability Zone in which the cluster is created.
    # All nodes belonging to this cluster are placed in the preferred Availability Zone. If you want to create your
    # nodes across multiple Availability Zones, use PreferredAvailabilityZones .
    # Default: System chosen Availability Zone.
    preferred_availability_zone: Optional[str] = None
    # A list of the Availability Zones in which cache nodes are created. The order of the zones is not important.
    # This option is only supported on Memcached.
    preferred_availability_zones: Optional[List[str]] = None
    # The version number of the cache engine to be used for this cluster.
    engine_version: Optional[str] = None
    cache_parameter_group_name: Optional[str] = None

    # The name of the subnet group to be used for the cluster.
    cache_subnet_group_name: Optional[str] = None
    # If cache_subnet_group_name is None,
    # Read the cache_subnet_group_name from cache_subnet_group
    cache_subnet_group: Optional[CacheSubnetGroup] = None

    # A list of security group names to associate with this cluster.
    # Use this parameter only when you are creating a cluster outside of an Amazon Virtual Private Cloud (Amazon VPC).
    cache_security_group_names: Optional[List[str]] = None
    # One or more VPC security groups associated with the cluster.
    # Use this parameter only when you are creating a cluster in an Amazon Virtual Private Cloud (Amazon VPC).
    cache_security_group_ids: Optional[List[str]] = None
    # If cache_security_group_ids is None
    # Read the security_group_id from cache_security_groups
    cache_security_groups: Optional[List[SecurityGroup]] = None

    tags: Optional[List[Dict[str, str]]] = None
    snapshot_arns: Optional[List[str]] = None
    snapshot_name: Optional[str] = None
    preferred_maintenance_window: Optional[str] = None
    # The version number of the cache engine to be used for this cluster.
    port: Optional[int] = None
    notification_topic_arn: Optional[str] = None
    auto_minor_version_upgrade: Optional[bool] = None
    snapshot_retention_limit: Optional[int] = None
    snapshot_window: Optional[str] = None
    # The password used to access a password protected server.
    # Password constraints:
    # - Must be only printable ASCII characters.
    # - Must be at least 16 characters and no more than 128 characters in length.
    # - The only permitted printable special characters are !, &, #, $, ^, <, >, and -.
    # Other printable special characters cannot be used in the AUTH token.
    # - For more information, see AUTH password at http://redis.io/commands/AUTH.
    # Provide AUTH_TOKEN here or as AUTH_TOKEN in secrets_file
    auth_token: Optional[str] = None
    outpost_mode: Optional[Literal["single-outpost", "cross-outpost"]] = None
    preferred_outpost_arn: Optional[str] = None
    preferred_outpost_arns: Optional[List[str]] = None
    log_delivery_configurations: Optional[List[Dict[str, Any]]] = None
    transit_encryption_enabled: Optional[bool] = None
    network_type: Optional[Literal["ipv4", "ipv6", "dual_stack"]] = None
    ip_discovery: Optional[Literal["ipv4", "ipv6"]] = None

    # The user-supplied name of a final cluster snapshot
    final_snapshot_identifier: Optional[str] = None

    # Read secrets from a file in yaml format
    secrets_file: Optional[Path] = None

    # The following attributes are used for update function
    cache_node_ids_to_remove: Optional[List[str]] = None
    new_availability_zone: Optional[List[str]] = None
    security_group_ids: Optional[List[str]] = None
    notification_topic_status: Optional[str] = None
    apply_immediately: Optional[bool] = None
    auth_token_update_strategy: Optional[Literal["SET", "ROTATE", "DELETE"]] = None

    def get_cache_cluster_id(self):
        return self.cache_cluster_id or self.name

    def get_auth_token(self) -> Optional[str]:
        auth_token = self.auth_token
        if auth_token is None and self.secrets_file is not None:
            # read from secrets_file
            secret_data = self.get_secret_file_data()
            if secret_data is not None:
                auth_token = secret_data.get("AUTH_TOKEN", auth_token)
        return auth_token

    def _create(self, aws_client: AwsApiClient) -> bool:
        """Creates the CacheCluster

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}

        # Get the CacheSubnetGroupName
        cache_subnet_group_name = self.cache_subnet_group_name
        if cache_subnet_group_name is None and self.cache_subnet_group is not None:
            cache_subnet_group_name = self.cache_subnet_group.name
            logger.debug(f"Using CacheSubnetGroup: {cache_subnet_group_name}")
        if cache_subnet_group_name is not None:
            not_null_args["CacheSubnetGroupName"] = cache_subnet_group_name

        cache_security_group_ids = self.cache_security_group_ids
        if cache_security_group_ids is None and self.cache_security_groups is not None:
            sg_ids = []
            for sg in self.cache_security_groups:
                sg_id = sg.get_security_group_id(aws_client)
                if sg_id is not None:
                    sg_ids.append(sg_id)
            if len(sg_ids) > 0:
                cache_security_group_ids = sg_ids
                logger.debug(f"Using SecurityGroups: {cache_security_group_ids}")
        if cache_security_group_ids is not None:
            not_null_args["SecurityGroupIds"] = cache_security_group_ids

        if self.replication_group_id is not None:
            not_null_args["ReplicationGroupId"] = self.replication_group_id
        if self.az_mode is not None:
            not_null_args["AZMode"] = self.az_mode
        if self.preferred_availability_zone is not None:
            not_null_args["PreferredAvailabilityZone"] = self.preferred_availability_zone
        if self.preferred_availability_zones is not None:
            not_null_args["PreferredAvailabilityZones"] = self.preferred_availability_zones
        if self.num_cache_nodes is not None:
            not_null_args["NumCacheNodes"] = self.num_cache_nodes
        if self.cache_node_type is not None:
            not_null_args["CacheNodeType"] = self.cache_node_type
        if self.engine is not None:
            not_null_args["Engine"] = self.engine
        if self.engine_version is not None:
            not_null_args["EngineVersion"] = self.engine_version
        if self.cache_parameter_group_name is not None:
            not_null_args["CacheParameterGroupName"] = self.cache_parameter_group_name
        if self.cache_security_group_names is not None:
            not_null_args["CacheSecurityGroupNames"] = self.cache_security_group_names
        if self.tags is not None:
            not_null_args["Tags"] = self.tags
        if self.snapshot_arns is not None:
            not_null_args["SnapshotArns"] = self.snapshot_arns
        if self.snapshot_name is not None:
            not_null_args["SnapshotName"] = self.snapshot_name
        if self.preferred_maintenance_window is not None:
            not_null_args["PreferredMaintenanceWindow"] = self.preferred_maintenance_window
        if self.port is not None:
            not_null_args["Port"] = self.port
        if self.notification_topic_arn is not None:
            not_null_args["NotificationTopicArn"] = self.notification_topic_arn
        if self.auto_minor_version_upgrade is not None:
            not_null_args["AutoMinorVersionUpgrade"] = self.auto_minor_version_upgrade
        if self.snapshot_retention_limit is not None:
            not_null_args["SnapshotRetentionLimit"] = self.snapshot_retention_limit
        if self.snapshot_window is not None:
            not_null_args["SnapshotWindow"] = self.snapshot_window
        if self.auth_token is not None:
            not_null_args["AuthToken"] = self.get_auth_token()
        if self.outpost_mode is not None:
            not_null_args["OutpostMode"] = self.outpost_mode
        if self.preferred_outpost_arn is not None:
            not_null_args["PreferredOutpostArn"] = self.preferred_outpost_arn
        if self.preferred_outpost_arns is not None:
            not_null_args["PreferredOutpostArns"] = self.preferred_outpost_arns
        if self.log_delivery_configurations is not None:
            not_null_args["LogDeliveryConfigurations"] = self.log_delivery_configurations
        if self.transit_encryption_enabled is not None:
            not_null_args["TransitEncryptionEnabled"] = self.transit_encryption_enabled
        if self.network_type is not None:
            not_null_args["NetworkType"] = self.network_type
        if self.ip_discovery is not None:
            not_null_args["IpDiscovery"] = self.ip_discovery

        # Create CacheCluster
        service_client = self.get_service_client(aws_client)
        try:
            create_response = service_client.create_cache_cluster(
                CacheClusterId=self.get_cache_cluster_id(),
                **not_null_args,
            )
            logger.debug(f"CacheCluster: {create_response}")
            resource_dict = create_response.get("CacheCluster", {})

            # Validate resource creation
            if resource_dict is not None:
                print_info(f"CacheCluster created: {self.get_cache_cluster_id()}")
                self.active_resource = create_response
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def post_create(self, aws_client: AwsApiClient) -> bool:
        # Wait for CacheCluster to be created
        if self.wait_for_create:
            try:
                print_info(f"Waiting for {self.get_resource_type()} to be active.")
                waiter = self.get_service_client(aws_client).get_waiter("cache_cluster_available")
                waiter.wait(
                    CacheClusterId=self.get_cache_cluster_id(),
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
        """Returns the CacheCluster

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")

        from botocore.exceptions import ClientError

        service_client = self.get_service_client(aws_client)
        try:
            cache_cluster_id = self.get_cache_cluster_id()
            describe_response = service_client.describe_cache_clusters(CacheClusterId=cache_cluster_id)
            logger.debug(f"CacheCluster: {describe_response}")
            resource_list = describe_response.get("CacheClusters", None)

            if resource_list is not None and isinstance(resource_list, list):
                for resource in resource_list:
                    _cluster_identifier = resource.get("CacheClusterId", None)
                    if _cluster_identifier == cache_cluster_id:
                        self.active_resource = resource
                        break
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return self.active_resource

    def _update(self, aws_client: AwsApiClient) -> bool:
        """Updates the CacheCluster

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        logger.debug(f"Updating {self.get_resource_type()}: {self.get_resource_name()}")

        cache_cluster_id = self.get_cache_cluster_id()
        if cache_cluster_id is None:
            logger.error("CacheClusterId is None")
            return False

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}
        if self.num_cache_nodes is not None:
            not_null_args["NumCacheNodes"] = self.num_cache_nodes
        if self.cache_node_ids_to_remove is not None:
            not_null_args["CacheNodeIdsToRemove"] = self.cache_node_ids_to_remove
        if self.az_mode is not None:
            not_null_args["AZMode"] = self.az_mode
        if self.new_availability_zone is not None:
            not_null_args["NewAvailabilityZone"] = self.new_availability_zone
        if self.cache_security_group_names is not None:
            not_null_args["CacheSecurityGroupNames"] = self.cache_security_group_names
        if self.security_group_ids is not None:
            not_null_args["SecurityGroupIds"] = self.security_group_ids
        if self.preferred_maintenance_window is not None:
            not_null_args["PreferredMaintenanceWindow"] = self.preferred_maintenance_window
        if self.notification_topic_arn is not None:
            not_null_args["NotificationTopicArn"] = self.notification_topic_arn
        if self.cache_parameter_group_name is not None:
            not_null_args["CacheParameterGroupName"] = self.cache_parameter_group_name
        if self.notification_topic_status is not None:
            not_null_args["NotificationTopicStatus"] = self.notification_topic_status
        if self.apply_immediately is not None:
            not_null_args["ApplyImmediately"] = self.apply_immediately
        if self.engine_version is not None:
            not_null_args["EngineVersion"] = self.engine_version
        if self.auto_minor_version_upgrade is not None:
            not_null_args["AutoMinorVersionUpgrade"] = self.auto_minor_version_upgrade
        if self.snapshot_retention_limit is not None:
            not_null_args["SnapshotRetentionLimit"] = self.snapshot_retention_limit
        if self.snapshot_window is not None:
            not_null_args["SnapshotWindow"] = self.snapshot_window
        if self.cache_node_type is not None:
            not_null_args["CacheNodeType"] = self.cache_node_type
        if self.auth_token is not None:
            not_null_args["AuthToken"] = self.get_auth_token()
        if self.auth_token_update_strategy is not None:
            not_null_args["AuthTokenUpdateStrategy"] = self.auth_token_update_strategy
        if self.log_delivery_configurations is not None:
            not_null_args["LogDeliveryConfigurations"] = self.log_delivery_configurations

        service_client = self.get_service_client(aws_client)
        try:
            modify_response = service_client.modify_cache_cluster(
                CacheClusterId=cache_cluster_id,
                **not_null_args,
            )
            logger.debug(f"CacheCluster: {modify_response}")
            resource_dict = modify_response.get("CacheCluster", {})

            # Validate resource creation
            if resource_dict is not None:
                print_info(f"CacheCluster updated: {self.get_cache_cluster_id()}")
                self.active_resource = modify_response
            return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be updated.")
            logger.error(e)
        return False

    def _delete(self, aws_client: AwsApiClient) -> bool:
        """Deletes the CacheCluster

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}
        if self.final_snapshot_identifier:
            not_null_args["FinalSnapshotIdentifier"] = self.final_snapshot_identifier

        service_client = self.get_service_client(aws_client)
        self.active_resource = None
        try:
            delete_response = service_client.delete_cache_cluster(
                CacheClusterId=self.get_cache_cluster_id(),
                **not_null_args,
            )
            logger.debug(f"CacheCluster: {delete_response}")
            return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be deleted.")
            logger.error("Please try again or delete resources manually.")
            logger.error(e)
        return False

    def post_delete(self, aws_client: AwsApiClient) -> bool:
        # Wait for CacheCluster to be deleted
        if self.wait_for_delete:
            try:
                print_info(f"Waiting for {self.get_resource_type()} to be deleted.")
                waiter = self.get_service_client(aws_client).get_waiter("cache_cluster_deleted")
                waiter.wait(
                    CacheClusterId=self.get_cache_cluster_id(),
                    WaiterConfig={
                        "Delay": self.waiter_delay,
                        "MaxAttempts": self.waiter_max_attempts,
                    },
                )
            except Exception as e:
                logger.error("Waiter failed.")
                logger.error(e)
        return True

    def get_cache_endpoint(self, aws_client: Optional[AwsApiClient] = None) -> Optional[str]:
        """Returns the CacheCluster endpoint

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        cache_endpoint = None
        try:
            client: AwsApiClient = aws_client or self.get_aws_client()
            cache_cluster_id = self.get_cache_cluster_id()
            describe_response = self.get_service_client(client).describe_cache_clusters(
                CacheClusterId=cache_cluster_id, ShowCacheNodeInfo=True
            )
            # logger.debug(f"CacheCluster: {describe_response}")
            resource_list = describe_response.get("CacheClusters", None)

            if resource_list is not None and isinstance(resource_list, list):
                for resource in resource_list:
                    _cluster_identifier = resource.get("CacheClusterId", None)
                    if _cluster_identifier == cache_cluster_id:
                        for node in resource.get("CacheNodes", []):
                            cache_endpoint = node.get("Endpoint", {}).get("Address", None)
                            if cache_endpoint is not None and isinstance(cache_endpoint, str):
                                return cache_endpoint
                        break
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return cache_endpoint

    def get_cache_port(self, aws_client: Optional[AwsApiClient] = None) -> Optional[int]:
        """Returns the CacheCluster port

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        cache_port = None
        try:
            client: AwsApiClient = aws_client or self.get_aws_client()
            cache_cluster_id = self.get_cache_cluster_id()
            describe_response = self.get_service_client(client).describe_cache_clusters(
                CacheClusterId=cache_cluster_id, ShowCacheNodeInfo=True
            )
            # logger.debug(f"CacheCluster: {describe_response}")
            resource_list = describe_response.get("CacheClusters", None)

            if resource_list is not None and isinstance(resource_list, list):
                for resource in resource_list:
                    _cluster_identifier = resource.get("CacheClusterId", None)
                    if _cluster_identifier == cache_cluster_id:
                        for node in resource.get("CacheNodes", []):
                            cache_port = node.get("Endpoint", {}).get("Port", None)
                            if cache_port is not None and isinstance(cache_port, int):
                                return cache_port
                        break
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return cache_port
