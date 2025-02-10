from typing import Any, Dict, List, Optional

from typing_extensions import Literal

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.cli.console import print_info
from agno.utils.log import logger


class EmrCluster(AwsResource):
    """
    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/emr.html
    """

    resource_type: Optional[str] = "EmrCluster"
    service_name: str = "emr"

    # Name of the cluster.
    name: str
    # The location in Amazon S3 to write the log files of the job flow.
    # If a value is not provided, logs are not created.
    log_uri: Optional[str] = None
    # The KMS key used for encrypting log files. If a value is not provided, the logs remain encrypted by AES-256.
    # This attribute is only available with Amazon EMR version 5.30.0 and later, excluding Amazon EMR 6.0.0.
    log_encryption_kms_key_id: Optional[str] = None
    # A JSON string for selecting additional features.
    additional_info: Optional[str] = None
    # The Amazon EMR release label, which determines the version of open-source application packages installed on the
    # cluster. Release labels are in the form emr-x.x.x,
    # where x.x.x is an Amazon EMR release version such as emr-5.14.0 .
    release_label: Optional[str] = None
    # A specification of the number and type of Amazon EC2 instances.
    instances: Optional[Dict[str, Any]] = None
    # A list of steps to run.
    steps: Optional[List[Dict[str, Any]]] = None
    # A list of bootstrap actions to run before Hadoop starts on the cluster nodes.
    bootstrap_actions: Optional[List[Dict[str, Any]]] = None
    # For Amazon EMR releases 3.x and 2.x. For Amazon EMR releases 4.x and later, use Applications.
    # A list of strings that indicates third-party software to use.
    supported_products: Optional[List[str]]
    new_supported_products: Optional[List[Dict[str, Any]]] = None
    # Applies to Amazon EMR releases 4.0 and later.
    # A case-insensitive list of applications for Amazon EMR to install and configure when launching the cluster.
    applications: Optional[List[Dict[str, Any]]] = None
    # For Amazon EMR releases 4.0 and later. The list of configurations supplied for the EMR cluster you are creating.
    configurations: Optional[List[Dict[str, Any]]] = None
    # Also called instance profile and EC2 role. An IAM role for an EMR cluster.
    # The EC2 instances of the cluster assume this role. The default role is EMR_EC2_DefaultRole.
    # In order to use the default role, you must have already created it using the CLI or console.
    job_flow_role: Optional[str] = None
    # he IAM role that Amazon EMR assumes in order to access Amazon Web Services resources on your behalf.
    service_role: Optional[str] = None
    # A list of tags to associate with a cluster and propagate to Amazon EC2 instances.
    tags: Optional[List[Dict[str, str]]] = None
    # The name of a security configuration to apply to the cluster.
    security_configuration: Optional[str] = None
    # An IAM role for automatic scaling policies. The default role is EMR_AutoScaling_DefaultRole.
    # The IAM role provides permissions that the automatic scaling feature requires to launch and terminate EC2
    # instances in an instance group.
    auto_scaling_role: Optional[str] = None
    scale_down_behavior: Optional[Literal["TERMINATE_AT_INSTANCE_HOUR", "TERMINATE_AT_TASK_COMPLETION"]] = None
    custom_ami_id: Optional[str] = None
    # The size, in GiB, of the Amazon EBS root device volume of the Linux AMI that is used for each EC2 instance.
    ebs_root_volume_size: Optional[int] = None
    repo_upgrade_on_boot: Optional[Literal["SECURITY", "NONE"]] = None
    # Attributes for Kerberos configuration when Kerberos authentication is enabled using a security configuration.
    kerberos_attributes: Optional[Dict[str, str]] = None
    # Specifies the number of steps that can be executed concurrently.
    # The default value is 1 . The maximum value is 256 .
    step_concurrency_level: Optional[int] = None
    # The specified managed scaling policy for an Amazon EMR cluster.
    managed_scaling_policy: Optional[Dict[str, Any]] = None
    placement_group_configs: Optional[List[Dict[str, Any]]] = None
    # The auto-termination policy defines the amount of idle time in seconds after which a cluster terminates.
    auto_termination_policy: Optional[Dict[str, int]] = None

    # provided by api on create
    # A unique identifier for the job flow.
    job_flow_id: Optional[str] = None
    # The Amazon Resource Name (ARN) of the cluster.
    cluster_arn: Optional[str] = None
    # ClusterSummary returned on read
    cluster_summary: Optional[Dict] = None

    def _create(self, aws_client: AwsApiClient) -> bool:
        """Creates the EmrCluster

        Args:
            aws_client: The AwsApiClient for the current cluster
        """

        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")
        try:
            # create a dict of args which are not null, otherwise aws type validation fails
            not_null_args: Dict[str, Any] = {}

            if self.log_uri:
                not_null_args["LogUri"] = self.log_uri
            if self.log_encryption_kms_key_id:
                not_null_args["LogEncryptionKmsKeyId"] = self.log_encryption_kms_key_id
            if self.additional_info:
                not_null_args["AdditionalInfo"] = self.additional_info
            if self.release_label:
                not_null_args["ReleaseLabel"] = self.release_label
            if self.instances:
                not_null_args["Instances"] = self.instances
            if self.steps:
                not_null_args["Steps"] = self.steps
            if self.bootstrap_actions:
                not_null_args["BootstrapActions"] = self.bootstrap_actions
            if self.supported_products:
                not_null_args["SupportedProducts"] = self.supported_products
            if self.new_supported_products:
                not_null_args["NewSupportedProducts"] = self.new_supported_products
            if self.applications:
                not_null_args["Applications"] = self.applications
            if self.configurations:
                not_null_args["Configurations"] = self.configurations
            if self.job_flow_role:
                not_null_args["JobFlowRole"] = self.job_flow_role
            if self.service_role:
                not_null_args["ServiceRole"] = self.service_role
            if self.tags:
                not_null_args["Tags"] = self.tags
            if self.security_configuration:
                not_null_args["SecurityConfiguration"] = self.security_configuration
            if self.auto_scaling_role:
                not_null_args["AutoScalingRole"] = self.auto_scaling_role
            if self.scale_down_behavior:
                not_null_args["ScaleDownBehavior"] = self.scale_down_behavior
            if self.custom_ami_id:
                not_null_args["CustomAmiId"] = self.custom_ami_id
            if self.ebs_root_volume_size:
                not_null_args["EbsRootVolumeSize"] = self.ebs_root_volume_size
            if self.repo_upgrade_on_boot:
                not_null_args["RepoUpgradeOnBoot"] = self.repo_upgrade_on_boot
            if self.kerberos_attributes:
                not_null_args["KerberosAttributes"] = self.kerberos_attributes
            if self.step_concurrency_level:
                not_null_args["StepConcurrencyLevel"] = self.step_concurrency_level
            if self.managed_scaling_policy:
                not_null_args["ManagedScalingPolicy"] = self.managed_scaling_policy
            if self.placement_group_configs:
                not_null_args["PlacementGroupConfigs"] = self.placement_group_configs
            if self.auto_termination_policy:
                not_null_args["AutoTerminationPolicy"] = self.auto_termination_policy

            # Get the service_client
            service_client = self.get_service_client(aws_client)

            # Create EmrCluster
            create_response = service_client.run_job_flow(
                Name=self.name,
                **not_null_args,
            )
            logger.debug(f"create_response type: {type(create_response)}")
            logger.debug(f"create_response: {create_response}")

            self.job_flow_id = create_response.get("JobFlowId", None)
            self.cluster_arn = create_response.get("ClusterArn", None)
            self.active_resource = create_response
            if self.active_resource is not None:
                print_info(f"{self.get_resource_type()}: {self.get_resource_name()} created")
                logger.debug(f"JobFlowId: {self.job_flow_id}")
                logger.debug(f"ClusterArn: {self.cluster_arn}")
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def post_create(self, aws_client: AwsApiClient) -> bool:
        ## Wait for Cluster to be created
        if self.wait_for_create:
            try:
                print_info("Waiting for EmrCluster to be active.")
                if self.job_flow_id is not None:
                    waiter = self.get_service_client(aws_client).get_waiter("cluster_running")
                    waiter.wait(
                        ClusterId=self.job_flow_id,
                        WaiterConfig={
                            "Delay": self.waiter_delay,
                            "MaxAttempts": self.waiter_max_attempts,
                        },
                    )
                else:
                    logger.warning("Skipping waiter, No ClusterId found")
            except Exception as e:
                logger.error("Waiter failed.")
                logger.error(e)
        return True

    def _read(self, aws_client: AwsApiClient) -> Optional[Any]:
        """Returns the EmrCluster

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        from botocore.exceptions import ClientError

        logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")
        try:
            service_client = self.get_service_client(aws_client)
            list_response = service_client.list_clusters()
            # logger.debug(f"list_response type: {type(list_response)}")
            # logger.debug(f"list_response: {list_response}")

            cluster_summary_list = list_response.get("Clusters", None)
            if cluster_summary_list is not None and isinstance(cluster_summary_list, list):
                for _cluster_summary in cluster_summary_list:
                    cluster_name = _cluster_summary.get("Name", None)
                    if cluster_name == self.name:
                        self.active_resource = _cluster_summary
                        break

            if self.active_resource is None:
                logger.debug(f"No {self.get_resource_type()} found")
                return None

            # logger.debug(f"EmrCluster: {self.active_resource}")
            self.job_flow_id = self.active_resource.get("Id", None)
            self.cluster_arn = self.active_resource.get("ClusterArn", None)
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return self.active_resource

    def _delete(self, aws_client: AwsApiClient) -> bool:
        """Deletes the EmrCluster

        Args:
            aws_client: The AwsApiClient for the current cluster
        """

        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")
        try:
            # populate self.job_flow_id
            self._read(aws_client)

            service_client = self.get_service_client(aws_client)
            self.active_resource = None

            if self.job_flow_id:
                service_client.terminate_job_flows(JobFlowIds=[self.job_flow_id])
                print_info(f"{self.get_resource_type()}: {self.get_resource_name()} deleted")
            else:
                logger.error("Could not find cluster id")
            return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be deleted.")
            logger.error("Please try again or delete resources manually.")
            logger.error(e)
        return False
