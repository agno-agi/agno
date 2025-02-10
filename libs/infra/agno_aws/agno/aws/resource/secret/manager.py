import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.cli.console import print_info
from agno.utils.log import logger


class SecretsManager(AwsResource):
    """
    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/secretsmanager.html
    """

    resource_type: Optional[str] = "Secret"
    service_name: str = "secretsmanager"

    # The name of the secret.
    name: str
    client_request_token: Optional[str] = None
    # The description of the secret.
    description: Optional[str] = None
    kms_key_id: Optional[str] = None
    # The binary data to encrypt and store in the new version of the secret.
    # We recommend that you store your binary data in a file and then pass the contents of the file as a parameter.
    secret_binary: Optional[bytes] = None
    # The text data to encrypt and store in this new version of the secret.
    # We recommend you use a JSON structure of key/value pairs for your secret value.
    # Either SecretString or SecretBinary must have a value, but not both.
    secret_string: Optional[str] = None
    # A list of tags to attach to the secret.
    tags: Optional[List[Dict[str, str]]] = None
    # A list of Regions and KMS keys to replicate secrets.
    add_replica_regions: Optional[List[Dict[str, str]]] = None
    # Specifies whether to overwrite a secret with the same name in the destination Region.
    force_overwrite_replica_secret: Optional[str] = None

    # Read secret key/value pairs from yaml files
    secret_files: Optional[List[Path]] = None
    # Read secret key/value pairs from yaml files in a directory
    secrets_dir: Optional[Path] = None
    # Force delete the secret without recovery
    force_delete: Optional[bool] = True

    # Provided by api on create
    secret_arn: Optional[str] = None
    secret_name: Optional[str] = None
    secret_value: Optional[dict] = None

    cached_secret: Optional[Dict[str, Any]] = None

    def read_secrets_from_files(self) -> Dict[str, Any]:
        """Reads secrets from files"""
        from agno.utils.yaml_io import read_yaml_file

        secret_dict: Dict[str, Any] = {}
        if self.secret_files:
            for f in self.secret_files:
                _s = read_yaml_file(f)
                if _s is not None:
                    secret_dict.update(_s)
        if self.secrets_dir:
            for f in self.secrets_dir.glob("*.yaml"):
                _s = read_yaml_file(f)
                if _s is not None:
                    secret_dict.update(_s)
            for f in self.secrets_dir.glob("*.yml"):
                _s = read_yaml_file(f)
                if _s is not None:
                    secret_dict.update(_s)
        return secret_dict

    def _create(self, aws_client: AwsApiClient) -> bool:
        """Creates the SecretsManager

        Args:
            aws_client: The AwsApiClient for the current secret
        """
        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")

        # Step 1: Read secrets from files
        secret_dict: Dict[str, Any] = self.read_secrets_from_files()

        # Step 2: Add secret_string if provided
        if self.secret_string is not None:
            secret_dict.update(json.loads(self.secret_string))

        # Step 3: Build secret_string
        secret_string: Optional[str] = json.dumps(secret_dict) if len(secret_dict) > 0 else None

        # Step 4: Build SecretsManager configuration
        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}
        if self.client_request_token:
            not_null_args["ClientRequestToken"] = self.client_request_token
        if self.description:
            not_null_args["Description"] = self.description
        if self.kms_key_id:
            not_null_args["KmsKeyId"] = self.kms_key_id
        if self.secret_binary:
            not_null_args["SecretBinary"] = self.secret_binary
        if secret_string:
            not_null_args["SecretString"] = secret_string
        if self.tags:
            not_null_args["Tags"] = self.tags
        if self.add_replica_regions:
            not_null_args["AddReplicaRegions"] = self.add_replica_regions
        if self.force_overwrite_replica_secret:
            not_null_args["ForceOverwriteReplicaSecret"] = self.force_overwrite_replica_secret

        # Step 3: Create SecretsManager
        service_client = self.get_service_client(aws_client)
        try:
            created_resource = service_client.create_secret(
                Name=self.name,
                **not_null_args,
            )
            logger.debug(f"SecretsManager: {created_resource}")

            # Validate SecretsManager creation
            self.secret_arn = created_resource.get("ARN", None)
            self.secret_name = created_resource.get("Name", None)
            logger.debug(f"secret_arn: {self.secret_arn}")
            logger.debug(f"secret_name: {self.secret_name}")
            if self.secret_arn is not None:
                self.cached_secret = secret_dict
                self.active_resource = created_resource
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def _read(self, aws_client: AwsApiClient) -> Optional[Any]:
        """Returns the SecretsManager

        Args:
            aws_client: The AwsApiClient for the current secret
        """
        logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")

        from botocore.exceptions import ClientError

        service_client = self.get_service_client(aws_client)
        try:
            describe_response = service_client.describe_secret(SecretId=self.name)
            logger.debug(f"SecretsManager: {describe_response}")

            self.secret_arn = describe_response.get("ARN", None)
            self.secret_name = describe_response.get("Name", None)
            describe_response.get("DeletedDate", None)
            logger.debug(f"secret_arn: {self.secret_arn}")
            logger.debug(f"secret_name: {self.secret_name}")
            # logger.debug(f"secret_deleted_date: {secret_deleted_date}")
            if self.secret_arn is not None:
                # print_info(f"SecretsManager available: {self.name}")
                self.active_resource = describe_response
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return self.active_resource

    def _delete(self, aws_client: AwsApiClient) -> bool:
        """Deletes the SecretsManager

        Args:
            aws_client: The AwsApiClient for the current secret
        """
        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")

        service_client = self.get_service_client(aws_client)
        self.active_resource = None
        self.secret_value = None
        try:
            delete_response = service_client.delete_secret(
                SecretId=self.name, ForceDeleteWithoutRecovery=self.force_delete
            )
            logger.debug(f"SecretsManager: {delete_response}")
            return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be deleted.")
            logger.error("Please try again or delete resources manually.")
            logger.error(e)
        return False

    def _update(self, aws_client: AwsApiClient) -> bool:
        """Update SecretsManager"""
        print_info(f"Updating {self.get_resource_type()}: {self.get_resource_name()}")

        # Initialize final secret_dict
        secret_dict: Dict[str, Any] = {}

        # Step 1: Read secrets from AWS SecretsManager
        existing_secret_dict = self.get_secrets_as_dict()
        # logger.debug(f"existing_secret_dict: {existing_secret_dict}")
        if existing_secret_dict is not None:
            secret_dict.update(existing_secret_dict)

        # Step 2: Read secrets from files
        new_secret_dict: Dict[str, Any] = self.read_secrets_from_files()
        if len(new_secret_dict) > 0:
            secret_dict.update(new_secret_dict)

        # Step 3: Add secret_string is provided
        if self.secret_string is not None:
            secret_dict.update(json.loads(self.secret_string))

        # Step 3: Update AWS SecretsManager
        service_client = self.get_service_client(aws_client)
        self.active_resource = None
        self.secret_value = None
        try:
            create_response = service_client.update_secret(
                SecretId=self.name,
                SecretString=json.dumps(secret_dict),
            )
            logger.debug(f"SecretsManager: {create_response}")
            return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be Updated.")
            logger.error(e)
        return False

    def get_secrets_as_dict(self, aws_client: Optional[AwsApiClient] = None) -> Optional[Dict[str, Any]]:
        """Get secret value

        Args:
            aws_client: The AwsApiClient for the current secret
        """
        from botocore.exceptions import ClientError

        if self.cached_secret is not None:
            return self.cached_secret

        logger.debug(f"Getting {self.get_resource_type()}: {self.get_resource_name()}")
        client: AwsApiClient = aws_client or self.get_aws_client()
        service_client = self.get_service_client(client)
        try:
            secret_value = service_client.get_secret_value(SecretId=self.name)
            # logger.debug(f"SecretsManager: {secret_value}")

            if secret_value is None:
                logger.warning(f"Secret Empty: {self.name}")
                return None

            self.secret_value = secret_value
            self.secret_arn = secret_value.get("ARN", None)
            self.secret_name = secret_value.get("Name", None)

            secret_string = secret_value.get("SecretString", None)
            if secret_string is not None:
                self.cached_secret = json.loads(secret_string)
                return self.cached_secret

            secret_binary = secret_value.get("SecretBinary", None)
            if secret_binary is not None:
                self.cached_secret = json.loads(secret_binary.decode("utf-8"))
                return self.cached_secret
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return None

    def get_secret_value(self, secret_name: str, aws_client: Optional[AwsApiClient] = None) -> Optional[Any]:
        secret_dict = self.get_secrets_as_dict(aws_client=aws_client)
        if secret_dict is not None:
            return secret_dict.get(secret_name, None)
        return None
