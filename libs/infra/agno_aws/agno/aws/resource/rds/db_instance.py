from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from typing_extensions import Literal

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.aws.resource.cloudformation.stack import CloudFormationStack
from agno.aws.resource.ec2.security_group import SecurityGroup
from agno.aws.resource.rds.db_subnet_group import DbSubnetGroup
from agno.aws.resource.secret.manager import SecretsManager
from agno.cli.console import print_info
from agno.utils.log import logger


class DbInstance(AwsResource):
    """
    The DBInstance can be an RDS DB instance, or it can be a DB instance in an Aurora DB cluster.

    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/rds.html
    """

    resource_type: Optional[str] = "DbInstance"
    service_name: str = "rds"

    # Name of the db instance.
    name: str
    # The name of the database engine to be used for this instance.
    engine: Union[
        str,
        Literal[
            "aurora",
            "aurora-mysql",
            "aurora-postgresql",
            "custom-oracle-ee",
            "custom-sqlserver-ee",
            "custom-sqlserver-se",
            "custom-sqlserver-web",
            "mariadb",
            "mysql",
            "oracle-ee",
            "oracle-ee-cdb",
            "oracle-se2",
            "oracle-se2-cdb",
            "postgres",
            "sqlserver-ee",
            "sqlserver-se",
            "sqlserver-ex",
            "sqlserver-web",
        ],
    ]
    # The version number of the database engine to use.
    engine_version: Optional[str] = None
    # Compute and memory capacity of the DB instance, for example db.m5.large.
    db_instance_class: Optional[str] = None

    # This is the name of the database to create when the DB instance is created.
    # Note: The meaning of this parameter differs according to the database engine you use.
    # Provide DB_NAME here or as DB_NAME in secrets_file
    db_name: Optional[str] = None
    # The identifier for this DB instance. This parameter is stored as a lowercase string.
    # If None, use the name as the db_instance_identifier
    # Constraints:
    # - Must contain from 1 to 63 letters, numbers, or hyphens.
    # - First character must be a letter.
    # - Can't end with a hyphen or contain two consecutive hyphens.
    db_instance_identifier: Optional[str] = None
    # The amount of storage in gibibytes (GiB) to allocate for the DB instance.
    allocated_storage: Optional[int] = None
    # The name of the DB parameter group to associate with this DB instance.
    db_parameter_group_name: Optional[str] = None

    # The port number on which the database accepts connections.
    port: Optional[int] = None

    # The name for the master user.
    # Provide MASTER_USERNAME here or as MASTER_USERNAME in secrets_file
    master_username: Optional[str] = None
    # The password for the master user.
    # The password can include any printable ASCII character except "/", """, or "@".
    # Provide MASTER_USER_PASSWORD here or as MASTER_USER_PASSWORD in secrets_file
    master_user_password: Optional[str] = None
    # Read secrets from a file in yaml format
    secrets_file: Optional[Path] = None
    # Read secret variables from AWS Secret
    aws_secret: Optional[SecretsManager] = None

    # The Availability Zone (AZ) where the database will be created.
    availability_zone: Optional[str] = None
    # A DB subnet group to associate with this DB instance.
    db_subnet_group_name: Optional[str] = None
    # If db_subnet_group_name is None,
    # Read the db_subnet_group_name from db_subnet_group
    db_subnet_group: Optional[DbSubnetGroup] = None

    # Specifies whether the DB instance is publicly accessible.
    # When the DB instance is publicly accessible, its Domain Name System (DNS) endpoint resolves to the private IP
    # from within the DB instance's virtual private cloud (VPC). It resolves to the public IP address from outside
    # the DB instance's VPC. Access to the DB instance is ultimately controlled by the security group it uses.
    # That public access is not permitted if the security group assigned to the DB instance doesn't permit it.
    #
    # When the DB instance isn't publicly accessible, it is an internal DB instance with a DNS name that resolves
    # to a private IP address.
    publicly_accessible: Optional[bool] = None
    # The identifier of the DB cluster that the instance will belong to.
    db_cluster_identifier: Optional[str] = None
    # Specifies the storage type to be associated with the DB instance.
    # Valid values: gp2 | gp3 | io1 | standard
    # If you specify io1 or gp3 , you must also include a value for the Iops parameter.
    # Default: io1 if the Iops parameter is specified, otherwise gp2
    storage_type: Optional[str] = None
    iops: Optional[int] = None

    # A list of VPC security groups to associate with this DB instance.
    vpc_security_group_ids: Optional[List[str]] = None
    # If vpc_security_group_ids is None,
    # Read the security_group_id from vpc_stack
    vpc_stack: Optional[CloudFormationStack] = None
    # Add security_group_ids from db_security_groups
    db_security_groups: Optional[List[SecurityGroup]] = None

    backup_retention_period: Optional[int] = None
    character_set_name: Optional[str] = None
    preferred_backup_window: Optional[str] = None
    # The time range each week during which system maintenance can occur, in Universal Coordinated Time (UTC).
    preferred_maintenance_window: Optional[str] = None
    # A value that indicates whether the DB instance is a Multi-AZ deployment.
    # You can't set the AvailabilityZone parameter if the DB instance is a Multi-AZ deployment.
    multi_az: Optional[bool] = None
    auto_minor_version_upgrade: Optional[bool] = None
    license_model: Optional[str] = None
    option_group_name: Optional[str] = None
    nchar_character_set_name: Optional[str] = None
    tags: Optional[List[Dict[str, str]]] = None
    tde_credential_arn: Optional[str] = None
    tde_credential_password: Optional[str] = None
    storage_encrypted: Optional[bool] = None
    kms_key_id: Optional[str] = None
    domain: Optional[str] = None
    copy_tags_to_snapshot: Optional[bool] = None
    monitoring_interval: Optional[int] = None
    monitoring_role_arn: Optional[str] = None
    domain_iam_role_name: Optional[str] = None
    promotion_tier: Optional[int] = None
    timezone: Optional[str] = None
    enable_iam_database_authentication: Optional[bool] = None
    enable_performance_insights: Optional[bool] = None
    performance_insights_kms_key_id: Optional[str] = None
    performance_insights_retention_period: Optional[int] = None
    enable_cloudwatch_logs_exports: Optional[List[str]] = None
    processor_features: Optional[List[Dict[str, str]]] = None
    # A value that indicates whether the DB instance has deletion protection enabled. The database can't be deleted
    # when deletion protection is enabled. By default, deletion protection isn't enabled.
    deletion_protection: Optional[bool] = None
    # The upper limit in gibibytes (GiB) to which Amazon RDS can automatically scale the storage of the DB instance.
    max_allocated_storage: Optional[int] = None
    enable_customer_owned_ip: Optional[bool] = None
    custom_iam_instance_profile: Optional[str] = None
    backup_target: Optional[str] = None
    network_type: Optional[str] = None
    storage_throughput: Optional[int] = None
    ca_certificate_identifier: Optional[str] = None
    db_system_id: Optional[str] = None
    dedicated_log_volume: Optional[bool] = None

    # Specifies whether to manage the master user password with Amazon Web Services Secrets Manager.
    # Constraints:
    # Can’t manage the master user password with Amazon Web Services Secrets Manager if MasterUserPassword is specified.
    manage_master_user_password: Optional[bool] = None
    # The Amazon Web Services KMS key identifier to encrypt a secret that is automatically generated and
    # managed in Amazon Web Services Secrets Manager.
    master_user_secret_kms_key_id: Optional[str] = None

    # Parameters for delete function
    # Skip the creation of a final DB snapshot before the instance is deleted.
    # If skip_final_snapshot = True, no DB snapshot is created.
    # If skip_final_snapshot = None | False, a DB snapshot is created before the instance is deleted.
    #   You must specify a FinalDBSnapshotIdentifier parameter
    #   if skip_final_snapshot = None | False
    skip_final_snapshot: Optional[bool] = True
    # The DB cluster snapshot identifier of the new DB cluster snapshot created when SkipFinalSnapshot is disabled.
    final_db_snapshot_identifier: Optional[str] = None
    # Specifies whether to remove automated backups immediately after the DB cluster is deleted.
    # The default is to remove automated backups immediately after the DB cluster is deleted.
    delete_automated_backups: Optional[bool] = None

    # Parameters for update function
    apply_immediately: Optional[bool] = True
    allow_major_version_upgrade: Optional[bool] = None
    new_db_instance_identifier: Optional[str] = None
    db_port_number: Optional[int] = None
    cloudwatch_logs_export_configuration: Optional[Dict[str, Any]] = None
    use_default_processor_features: Optional[bool] = None
    certificate_rotation_restart: Optional[bool] = None
    replica_mode: Optional[str] = None
    aws_backup_recovery_point_arn: Optional[str] = None
    automation_mode: Optional[str] = None
    resume_full_automation_mode_minutes: Optional[int] = None
    rotate_master_user_password: Optional[bool] = None

    # Cache secret_data
    cached_secret_data: Optional[Dict[str, Any]] = None

    def get_db_instance_identifier(self):
        return self.db_instance_identifier or self.name

    def get_master_username(self, aws_client: Optional[AwsApiClient] = None) -> Optional[str]:
        master_username = self.master_username
        if master_username is None and self.secrets_file is not None:
            # read from secrets_file
            secret_data = self.get_secret_file_data()
            if secret_data is not None:
                master_username = secret_data.get("MASTER_USERNAME", master_username)
        if master_username is None and self.aws_secret is not None:
            # read from aws_secret
            logger.debug(f"Reading MASTER_USERNAME from secret: {self.aws_secret.name}")
            master_username = self.aws_secret.get_secret_value("MASTER_USERNAME", aws_client=aws_client)

        return master_username

    def get_master_user_password(self, aws_client: Optional[AwsApiClient] = None) -> Optional[str]:
        master_user_password = self.master_user_password
        if master_user_password is None and self.secrets_file is not None:
            # read from secrets_file
            secret_data = self.get_secret_file_data()
            if secret_data is not None:
                master_user_password = secret_data.get("MASTER_USER_PASSWORD", master_user_password)
        if master_user_password is None and self.aws_secret is not None:
            # read from aws_secret
            logger.debug(f"Reading MASTER_USER_PASSWORD from secret: {self.aws_secret.name}")
            master_user_password = self.aws_secret.get_secret_value("MASTER_USER_PASSWORD", aws_client=aws_client)

        return master_user_password

    def get_db_name(self, aws_client: Optional[AwsApiClient] = None) -> Optional[str]:
        db_name = self.db_name
        if db_name is None and self.secrets_file is not None:
            # read from secrets_file
            secret_data = self.get_secret_file_data()
            if secret_data is not None:
                db_name = secret_data.get("DB_NAME", db_name)
                if db_name is None:
                    db_name = secret_data.get("DATABASE_NAME", db_name)
        if db_name is None and self.aws_secret is not None:
            # read from aws_secret
            logger.debug(f"Reading DB_NAME from secret: {self.aws_secret.name}")
            db_name = self.aws_secret.get_secret_value("DB_NAME", aws_client=aws_client)
            if db_name is None:
                logger.debug(f"Reading DATABASE_NAME from secret: {self.aws_secret.name}")
                db_name = self.aws_secret.get_secret_value("DATABASE_NAME", aws_client=aws_client)
        return db_name

    def get_database_name(self) -> Optional[str]:
        # Alias for get_db_name because db_instances use `db_name` and db_clusters use `database_name`
        return self.get_db_name()

    def _create(self, aws_client: AwsApiClient) -> bool:
        """Creates the DbInstance

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}

        # Step 1: Get the VpcSecurityGroupIds
        vpc_security_group_ids = self.vpc_security_group_ids
        if vpc_security_group_ids is None and self.vpc_stack is not None:
            vpc_stack_sg = self.vpc_stack.get_security_group(aws_client=aws_client)
            if vpc_stack_sg is not None:
                vpc_security_group_ids = [vpc_stack_sg]
        if self.db_security_groups is not None:
            sg_ids = []
            for sg in self.db_security_groups:
                sg_id = sg.get_security_group_id(aws_client)
                if sg_id is not None:
                    sg_ids.append(sg_id)
            if len(sg_ids) > 0:
                if vpc_security_group_ids is None:
                    vpc_security_group_ids = []
                vpc_security_group_ids.extend(sg_ids)
        if vpc_security_group_ids is not None:
            logger.debug(f"Using SecurityGroups: {vpc_security_group_ids}")
            not_null_args["VpcSecurityGroupIds"] = vpc_security_group_ids

        # Step 2: Get the DbSubnetGroupName
        db_subnet_group_name = self.db_subnet_group_name
        if db_subnet_group_name is None and self.db_subnet_group is not None:
            db_subnet_group_name = self.db_subnet_group.name
            logger.debug(f"Using DbSubnetGroup: {db_subnet_group_name}")
        if db_subnet_group_name is not None:
            not_null_args["DBSubnetGroupName"] = db_subnet_group_name

        db_name = self.get_db_name()
        if db_name:
            not_null_args["DBName"] = db_name

        master_username = self.get_master_username()
        if master_username:
            not_null_args["MasterUsername"] = master_username
        master_user_password = self.get_master_user_password()
        if master_user_password:
            not_null_args["MasterUserPassword"] = master_user_password

        if self.allocated_storage:
            not_null_args["AllocatedStorage"] = self.allocated_storage
        if self.db_instance_class:
            not_null_args["DBInstanceClass"] = self.db_instance_class

        if self.availability_zone is not None:
            not_null_args["AvailabilityZone"] = self.availability_zone

        if self.preferred_maintenance_window:
            not_null_args["PreferredMaintenanceWindow"] = self.preferred_maintenance_window
        if self.db_parameter_group_name:
            not_null_args["DBParameterGroupName"] = self.db_parameter_group_name
        if self.backup_retention_period:
            not_null_args["BackupRetentionPeriod"] = self.backup_retention_period
        if self.preferred_backup_window:
            not_null_args["PreferredBackupWindow"] = self.preferred_backup_window
        if self.port:
            not_null_args["Port"] = self.port
        if self.multi_az:
            not_null_args["MultiAZ"] = self.multi_az
        if self.engine_version:
            not_null_args["EngineVersion"] = self.engine_version
        if self.auto_minor_version_upgrade:
            not_null_args["AutoMinorVersionUpgrade"] = self.auto_minor_version_upgrade
        if self.license_model:
            not_null_args["LicenseModel"] = self.license_model
        if self.iops:
            not_null_args["Iops"] = self.iops
        if self.option_group_name:
            not_null_args["OptionGroupName"] = self.option_group_name
        if self.character_set_name:
            not_null_args["CharacterSetName"] = self.character_set_name
        if self.nchar_character_set_name:
            not_null_args["NcharCharacterSetName"] = self.nchar_character_set_name
        if self.publicly_accessible:
            not_null_args["PubliclyAccessible"] = self.publicly_accessible
        if self.tags:
            not_null_args["Tags"] = self.tags
        if self.db_cluster_identifier:
            not_null_args["DBClusterIdentifier"] = self.db_cluster_identifier
        if self.storage_type:
            not_null_args["StorageType"] = self.storage_type
        if self.tde_credential_arn:
            not_null_args["TdeCredentialArn"] = self.tde_credential_arn
        if self.tde_credential_password:
            not_null_args["TdeCredentialPassword"] = self.tde_credential_password
        if self.storage_encrypted:
            not_null_args["StorageEncrypted"] = self.storage_encrypted
        if self.kms_key_id:
            not_null_args["KmsKeyId"] = self.kms_key_id
        if self.domain:
            not_null_args["Domain"] = self.domain
        if self.copy_tags_to_snapshot:
            not_null_args["CopyTagsToSnapshot"] = self.copy_tags_to_snapshot
        if self.monitoring_interval:
            not_null_args["MonitoringInterval"] = self.monitoring_interval
        if self.monitoring_role_arn:
            not_null_args["MonitoringRoleArn"] = self.monitoring_role_arn
        if self.domain_iam_role_name:
            not_null_args["DomainIAMRoleName"] = self.domain_iam_role_name
        if self.promotion_tier:
            not_null_args["PromotionTier"] = self.promotion_tier
        if self.timezone:
            not_null_args["Timezone"] = self.timezone
        if self.enable_iam_database_authentication:
            not_null_args["EnableIAMDatabaseAuthentication"] = self.enable_iam_database_authentication
        if self.enable_performance_insights:
            not_null_args["EnablePerformanceInsights"] = self.enable_performance_insights
        if self.performance_insights_kms_key_id:
            not_null_args["PerformanceInsightsKMSKeyId"] = self.performance_insights_kms_key_id
        if self.performance_insights_retention_period:
            not_null_args["PerformanceInsightsRetentionPeriod"] = self.performance_insights_retention_period
        if self.enable_cloudwatch_logs_exports:
            not_null_args["EnableCloudwatchLogsExports"] = self.enable_cloudwatch_logs_exports
        if self.processor_features:
            not_null_args["ProcessorFeatures"] = self.processor_features
        if self.deletion_protection:
            not_null_args["DeletionProtection"] = self.deletion_protection
        if self.max_allocated_storage:
            not_null_args["MaxAllocatedStorage"] = self.max_allocated_storage
        if self.enable_customer_owned_ip:
            not_null_args["EnableCustomerOwnedIp"] = self.enable_customer_owned_ip
        if self.custom_iam_instance_profile:
            not_null_args["CustomIamInstanceProfile"] = self.custom_iam_instance_profile
        if self.backup_target:
            not_null_args["BackupTarget"] = self.backup_target
        if self.network_type:
            not_null_args["NetworkType"] = self.network_type
        if self.storage_throughput:
            not_null_args["StorageThroughput"] = self.storage_throughput
        if self.ca_certificate_identifier:
            not_null_args["CACertificateIdentifier"] = self.ca_certificate_identifier
        if self.db_system_id:
            not_null_args["DBSystemId"] = self.db_system_id
        if self.dedicated_log_volume:
            not_null_args["DedicatedLogVolume"] = self.dedicated_log_volume

        if self.manage_master_user_password:
            not_null_args["ManageMasterUserPassword"] = self.manage_master_user_password
        if self.master_user_secret_kms_key_id:
            not_null_args["MasterUserSecretKmsKeyId"] = self.master_user_secret_kms_key_id

        # Step 3: Create DBInstance
        service_client = self.get_service_client(aws_client)
        try:
            create_response = service_client.create_db_instance(
                DBInstanceIdentifier=self.get_db_instance_identifier(),
                Engine=self.engine,
                **not_null_args,
            )
            logger.debug(f"Response: {create_response}")
            resource_dict = create_response.get("DBInstance", {})

            # Validate resource creation
            if resource_dict is not None:
                logger.debug(f"DBInstance created: {self.get_db_instance_identifier()}")
                self.active_resource = resource_dict
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def post_create(self, aws_client: AwsApiClient) -> bool:
        # Wait for DbInstance to be created
        if self.wait_for_create:
            try:
                print_info(f"Waiting for {self.get_resource_type()} to be active.")
                waiter = self.get_service_client(aws_client).get_waiter("db_instance_available")
                waiter.wait(
                    DBInstanceIdentifier=self.get_db_instance_identifier(),
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
        """Returns the DbInstance

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")

        from botocore.exceptions import ClientError

        service_client = self.get_service_client(aws_client)
        try:
            resource_identifier = self.get_db_instance_identifier()
            describe_response = service_client.describe_db_instances(DBInstanceIdentifier=resource_identifier)
            # logger.debug(f"DbInstance: {describe_response}")
            resources_list = describe_response.get("DBInstances", None)

            if resources_list is not None and isinstance(resources_list, list):
                for _resource in resources_list:
                    _identifier = _resource.get("DBInstanceIdentifier", None)
                    if _identifier == resource_identifier:
                        self.active_resource = _resource
                        break
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return self.active_resource

    def _delete(self, aws_client: AwsApiClient) -> bool:
        """Deletes the DbInstance

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")

        service_client = self.get_service_client(aws_client)
        self.active_resource = None

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}
        if self.final_db_snapshot_identifier:
            not_null_args["FinalDBSnapshotIdentifier"] = self.final_db_snapshot_identifier
        if self.delete_automated_backups:
            not_null_args["DeleteAutomatedBackups"] = self.delete_automated_backups

        try:
            db_instance_identifier = self.get_db_instance_identifier()
            delete_response = service_client.delete_db_instance(
                DBInstanceIdentifier=db_instance_identifier,
                SkipFinalSnapshot=self.skip_final_snapshot,
                **not_null_args,
            )
            logger.debug(f"Response: {delete_response}")
            resource_dict = delete_response.get("DBInstance", {})

            # Validate resource creation
            if resource_dict is not None:
                logger.debug(f"DBInstance deleted: {self.get_db_instance_identifier()}")
                self.active_resource = resource_dict
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be deleted.")
            logger.error("Please try again or delete resources manually.")
            logger.error(e)
        return False

    def post_delete(self, aws_client: AwsApiClient) -> bool:
        # Wait for DbInstance to be deleted
        if self.wait_for_delete:
            try:
                print_info(f"Waiting for {self.get_resource_type()} to be deleted.")
                waiter = self.get_service_client(aws_client).get_waiter("db_instance_deleted")
                waiter.wait(
                    DBInstanceIdentifier=self.get_db_instance_identifier(),
                    WaiterConfig={
                        "Delay": self.waiter_delay,
                        "MaxAttempts": self.waiter_max_attempts,
                    },
                )
            except Exception as e:
                logger.error("Waiter failed.")
                logger.error(e)
        return True

    def _update(self, aws_client: AwsApiClient) -> bool:
        """Updates the DbInstance"""

        print_info(f"Updating {self.get_resource_type()}: {self.get_resource_name()}")

        # Step 1: Get existing DBInstance
        db_instance = self.read(aws_client)

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {
            "ApplyImmediately": self.apply_immediately,
        }

        vpc_security_group_ids = self.vpc_security_group_ids
        if vpc_security_group_ids is None and self.vpc_stack is not None:
            vpc_stack_sg = self.vpc_stack.get_security_group(aws_client=aws_client)
            if vpc_stack_sg is not None:
                vpc_security_group_ids = [vpc_stack_sg]
        if self.db_security_groups is not None:
            sg_ids = []
            for sg in self.db_security_groups:
                sg_id = sg.get_security_group_id(aws_client)
                if sg_id is not None:
                    sg_ids.append(sg_id)
            if len(sg_ids) > 0:
                if vpc_security_group_ids is None:
                    vpc_security_group_ids = []
                vpc_security_group_ids.extend(sg_ids)
        # Check if vpc_security_group_ids has changed
        existing_vpc_security_group = db_instance.get("VpcSecurityGroups", [])
        existing_vpc_security_group_ids = []
        for existing_sg in existing_vpc_security_group:
            existing_vpc_security_group_ids.append(existing_sg.get("VpcSecurityGroupId", None))
        if vpc_security_group_ids is not None and vpc_security_group_ids != existing_vpc_security_group_ids:
            logger.info(f"Updating SecurityGroups: {vpc_security_group_ids}")
            not_null_args["VpcSecurityGroupIds"] = vpc_security_group_ids

        db_subnet_group_name = self.db_subnet_group_name
        if db_subnet_group_name is None and self.db_subnet_group is not None:
            db_subnet_group_name = self.db_subnet_group.name
        # Check if db_subnet_group_name has changed
        existing_db_subnet_group_name = db_instance.get("DBSubnetGroup", {}).get("DBSubnetGroupName", None)
        if db_subnet_group_name is not None and db_subnet_group_name != existing_db_subnet_group_name:
            logger.info(f"Updating DbSubnetGroup: {db_subnet_group_name}")
            not_null_args["DBSubnetGroupName"] = db_subnet_group_name

        master_user_password = self.get_master_user_password()
        if master_user_password:
            not_null_args["MasterUserPassword"] = master_user_password

        if self.allocated_storage:
            not_null_args["AllocatedStorage"] = self.allocated_storage
        if self.db_instance_class:
            not_null_args["DBInstanceClass"] = self.db_instance_class

        if self.db_parameter_group_name:
            not_null_args["DBParameterGroupName"] = self.db_parameter_group_name
        if self.backup_retention_period:
            not_null_args["BackupRetentionPeriod"] = self.backup_retention_period
        if self.preferred_backup_window:
            not_null_args["PreferredBackupWindow"] = self.preferred_backup_window
        if self.preferred_maintenance_window:
            not_null_args["PreferredMaintenanceWindow"] = self.preferred_maintenance_window
        if self.multi_az:
            not_null_args["MultiAZ"] = self.multi_az
        if self.engine_version:
            not_null_args["EngineVersion"] = self.engine_version
        if self.allow_major_version_upgrade:
            not_null_args["AllowMajorVersionUpgrade"] = self.allow_major_version_upgrade
        if self.auto_minor_version_upgrade:
            not_null_args["AutoMinorVersionUpgrade"] = self.auto_minor_version_upgrade
        if self.license_model:
            not_null_args["LicenseModel"] = self.license_model
        if self.iops:
            not_null_args["Iops"] = self.iops
        if self.option_group_name:
            not_null_args["OptionGroupName"] = self.option_group_name
        if self.new_db_instance_identifier:
            not_null_args["NewDBInstanceIdentifier"] = self.new_db_instance_identifier
        if self.storage_type:
            not_null_args["StorageType"] = self.storage_type
        if self.tde_credential_arn:
            not_null_args["TdeCredentialArn"] = self.tde_credential_arn
        if self.tde_credential_password:
            not_null_args["TdeCredentialPassword"] = self.tde_credential_password
        if self.ca_certificate_identifier:
            not_null_args["CACertificateIdentifier"] = self.ca_certificate_identifier
        if self.domain:
            not_null_args["Domain"] = self.domain
        if self.copy_tags_to_snapshot:
            not_null_args["CopyTagsToSnapshot"] = self.copy_tags_to_snapshot
        if self.monitoring_interval:
            not_null_args["MonitoringInterval"] = self.monitoring_interval
        if self.db_port_number:
            not_null_args["DBPortNumber"] = self.db_port_number
        if self.publicly_accessible:
            not_null_args["PubliclyAccessible"] = self.publicly_accessible
        if self.monitoring_role_arn:
            not_null_args["MonitoringRoleArn"] = self.monitoring_role_arn
        if self.domain_iam_role_name:
            not_null_args["DomainIAMRoleName"] = self.domain_iam_role_name
        if self.promotion_tier:
            not_null_args["PromotionTier"] = self.promotion_tier
        if self.enable_iam_database_authentication:
            not_null_args["EnableIAMDatabaseAuthentication"] = self.enable_iam_database_authentication
        if self.enable_performance_insights:
            not_null_args["EnablePerformanceInsights"] = self.enable_performance_insights
        if self.performance_insights_kms_key_id:
            not_null_args["PerformanceInsightsKMSKeyId"] = self.performance_insights_kms_key_id
        if self.performance_insights_retention_period:
            not_null_args["PerformanceInsightsRetentionPeriod"] = self.performance_insights_retention_period
        if self.cloudwatch_logs_export_configuration:
            not_null_args["CloudwatchLogsExportConfiguration"] = self.cloudwatch_logs_export_configuration
        if self.processor_features:
            not_null_args["ProcessorFeatures"] = self.processor_features
        if self.use_default_processor_features:
            not_null_args["UseDefaultProcessorFeatures"] = self.use_default_processor_features
        if self.deletion_protection:
            not_null_args["DeletionProtection"] = self.deletion_protection
        if self.max_allocated_storage:
            not_null_args["MaxAllocatedStorage"] = self.max_allocated_storage
        if self.certificate_rotation_restart:
            not_null_args["CertificateRotationRestart"] = self.certificate_rotation_restart
        if self.replica_mode:
            not_null_args["ReplicaMode"] = self.replica_mode
        if self.enable_customer_owned_ip:
            not_null_args["EnableCustomerOwnedIp"] = self.enable_customer_owned_ip
        if self.aws_backup_recovery_point_arn:
            not_null_args["AwsBackupRecoveryPointArn"] = self.aws_backup_recovery_point_arn
        if self.automation_mode:
            not_null_args["AutomationMode"] = self.automation_mode
        if self.resume_full_automation_mode_minutes:
            not_null_args["ResumeFullAutomationModeMinutes"] = self.resume_full_automation_mode_minutes
        if self.network_type:
            not_null_args["NetworkType"] = self.network_type
        if self.storage_throughput:
            not_null_args["StorageThroughput"] = self.storage_throughput
        if self.manage_master_user_password:
            not_null_args["ManageMasterUserPassword"] = self.manage_master_user_password
        if self.rotate_master_user_password:
            not_null_args["RotateMasterUserPassword"] = self.rotate_master_user_password
        if self.master_user_secret_kms_key_id:
            not_null_args["MasterUserSecretKmsKeyId"] = self.master_user_secret_kms_key_id

        # Step 2: Update DBInstance
        service_client = self.get_service_client(aws_client)
        try:
            update_response = service_client.modify_db_instance(
                DBInstanceIdentifier=self.get_db_instance_identifier(),
                **not_null_args,
            )
            logger.debug(f"Response: {update_response}")
            resource_dict = update_response.get("DBInstance", {})

            # Validate resource update
            if resource_dict is not None:
                print_info(f"DBInstance updated: {self.get_resource_name()}")
                self.active_resource = update_response
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def get_db_endpoint(self, aws_client: Optional[AwsApiClient] = None) -> Optional[str]:
        """Returns the DbInstance endpoint

        Returns:
            The DbInstance endpoint
        """
        logger.debug(f"Getting endpoint for {self.get_resource_name()}")
        _db_endpoint: Optional[str] = None
        if self.active_resource:
            _db_endpoint = self.active_resource.get("Endpoint", {}).get("Address", None)
        if _db_endpoint is None:
            client: AwsApiClient = aws_client or self.get_aws_client()
            resource = self._read(aws_client=client)
            if resource is not None:
                _db_endpoint = resource.get("Endpoint", {}).get("Address", None)
        if _db_endpoint is None:
            resource = self.read_resource_from_file()
            if resource is not None:
                _db_endpoint = resource.get("Endpoint", {}).get("Address", None)
        logger.debug(f"DBInstance Endpoint: {_db_endpoint}")
        return _db_endpoint

    def get_db_port(self, aws_client: Optional[AwsApiClient] = None) -> Optional[str]:
        """Returns the DbInstance port

        Returns:
            The DbInstance port
        """
        logger.debug(f"Getting port for {self.get_resource_name()}")
        _db_port: Optional[str] = None
        if self.active_resource:
            _db_port = self.active_resource.get("Endpoint", {}).get("Port", None)
        if _db_port is None:
            client: AwsApiClient = aws_client or self.get_aws_client()
            resource = self._read(aws_client=client)
            if resource is not None:
                _db_port = resource.get("Endpoint", {}).get("Port", None)
        if _db_port is None:
            resource = self.read_resource_from_file()
            if resource is not None:
                _db_port = resource.get("Endpoint", {}).get("Port", None)
        logger.debug(f"DBInstance Port: {_db_port}")
        return _db_port
