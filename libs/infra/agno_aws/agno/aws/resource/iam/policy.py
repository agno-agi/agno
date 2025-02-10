from typing import Any, Dict, List, Optional

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.cli.console import print_info
from agno.utils.log import logger


class IamPolicy(AwsResource):
    """
    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/iam.html#policy
    """

    resource_type: Optional[str] = "IamPolicy"
    service_name: str = "iam"

    # PolicyName
    # The friendly name of the policy.
    name: str
    # The JSON policy document that you want to use as the content for the new policy.
    # You must provide policies in JSON format in IAM.
    # However, for CloudFormation templates formatted in YAML, you can provide the policy in JSON or YAML format.
    # CloudFormation always converts a YAML policy to JSON format before submitting it to IAM.
    policy_document: str
    # The path for the policy. This parameter is optional. If it is not included, it defaults to a slash (/).
    path: Optional[str] = None
    # A friendly description of the policy.
    description: Optional[str] = None
    # A list of tags that you want to attach to the new policy. Each tag consists of a key name and an associated value.
    tags: Optional[List[Dict[str, str]]] = None

    arn: Optional[str] = None

    def _create(self, aws_client: AwsApiClient) -> bool:
        """Creates the IamPolicy

        Args:
            aws_client: The AwsApiClient for the current cluster
        """

        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")
        try:
            # create a dict of args which are not null, otherwise aws type validation fails
            not_null_args: Dict[str, Any] = {}
            if self.path:
                not_null_args["Path"] = self.path
            if self.description:
                not_null_args["Description"] = self.description
            if self.tags:
                not_null_args["Tags"] = self.tags

            # Create Policy
            service_resource = self.get_service_resource(aws_client)
            policy = service_resource.create_policy(
                PolicyName=self.name,
                PolicyDocument=self.policy_document,
                **not_null_args,
            )
            # logger.debug(f"Policy: {policy}")

            # Validate Policy creation
            create_date = policy.create_date
            self.arn = policy.arn
            logger.debug(f"create_date: {create_date}")
            logger.debug(f"arn: {self.arn}")
            if create_date is not None:
                print_info(f"Policy created: {self.name}")
                self.active_resource = policy
                return True
            logger.error("Policy could not be created")
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def post_create(self, aws_client: AwsApiClient) -> bool:
        # Wait for Policy to be created
        if self.wait_for_create:
            try:
                print_info(f"Waiting for {self.get_resource_type()} to be created.")
                if self.arn is not None:
                    waiter = self.get_service_client(aws_client).get_waiter("policy_exists")
                    waiter.wait(
                        PolicyArn=self.arn,
                        WaiterConfig={
                            "Delay": self.waiter_delay,
                            "MaxAttempts": self.waiter_max_attempts,
                        },
                    )
                else:
                    logger.warning("Skipping waiter, No Policy ARN found")
            except Exception as e:
                logger.error("Waiter failed.")
                logger.error(e)
        return True

    def _read(self, aws_client: AwsApiClient) -> Optional[Any]:
        """Returns the IamPolicy

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        from botocore.exceptions import ClientError

        logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")
        try:
            service_resource = self.get_service_resource(aws_client)
            policy = None
            for _policy in service_resource.policies.all():
                if _policy.policy_name == self.name:
                    policy = _policy
                    break

            if policy is None:
                logger.debug("No Policy found")
                return None

            policy.load()
            create_date = policy.create_date
            self.arn = policy.arn
            logger.debug(f"create_date: {create_date}")
            logger.debug(f"arn: {self.arn}")
            if create_date is not None:
                logger.debug(f"Policy found: {policy.policy_name}")
                self.active_resource = policy
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return self.active_resource

    def _delete(self, aws_client: AwsApiClient) -> bool:
        """Deletes the IamPolicy

        Args:
            aws_client: The AwsApiClient for the current cluster
        """

        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")
        try:
            policy = self._read(aws_client)
            # logger.debug(f"Policy: {policy}")
            # logger.debug(f"Policy type: {type(policy)}")
            self.active_resource = None

            if policy is None:
                logger.warning(f"No {self.get_resource_type()} to delete")
                return True

            # Before you can delete a managed policy,
            # you must first detach the policy from all users, groups, and roles
            # that it is attached to. In addition, you must delete all
            # the policy's versions.

            # detach all roles
            roles = policy.attached_roles.all()
            for role in roles:
                print_info(f"Detaching policy from role: {role}")
                policy.detach_role(RoleName=role.name)

            # detach all users
            users = policy.attached_users.all()
            for user in users:
                print_info(f"Detaching policy from user: {user}")
                policy.detach_user(UserName=user.name)

            # detach all groups
            groups = policy.attached_groups.all()
            for group in groups:
                print_info(f"Detaching policy from group: {group}")
                policy.detach_group(GroupName=group.name)

            # delete all versions
            default_version = policy.default_version
            versions = policy.versions.all()
            for version in versions:
                if version.version_id == default_version.version_id:
                    print_info(f"Skipping deleting default PolicyVersion: {version}")
                    continue
                print_info(f"Deleting PolicyVersion: {version}")
                version.delete()

            # delete policy
            policy.delete()
            return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be deleted.")
            logger.error("Please try again or delete resources manually.")
            logger.error(e)
        return False
