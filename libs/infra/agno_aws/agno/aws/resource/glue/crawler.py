from typing import Any, Dict, List, Optional

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.aws.resource.iam.role import IamRole
from agno.aws.resource.s3.bucket import S3Bucket
from agno.cli.console import print_info
from agno.utils.log import logger


class GlueS3Target(AwsResource):
    # The directory path in the S3 bucket to target
    dir: str = ""
    # The s3 bucket to target
    bucket: S3Bucket
    # A list of glob patterns used to exclude from the crawl.
    # For more information, see https://docs.aws.amazon.com/glue/latest/dg/add-crawler.html
    exclusions: Optional[List[str]] = None
    # The name of a connection which allows a job or crawler to access data in Amazon S3 within an
    # Amazon Virtual Private Cloud environment (Amazon VPC).
    connection_name: Optional[str] = None
    # Sets the number of files in each leaf folder to be crawled when crawling sample files in a dataset.
    # If not set, all the files are crawled. A valid value is an integer between 1 and 249.
    sample_size: Optional[int] = None
    # A valid Amazon SQS ARN. For example, arn:aws:sqs:region:account:sqs .
    event_queue_arn: Optional[str] = None
    # A valid Amazon dead-letter SQS ARN. For example, arn:aws:sqs:region:account:deadLetterQueue .
    dlq_event_queue_arn: Optional[str] = None


class GlueCrawler(AwsResource):
    """
    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/glue.html
    """

    resource_type: Optional[str] = "GlueCrawler"
    service_name: str = "glue"

    # Name of the crawler.
    name: str
    # The IAM role for the crawler
    iam_role: IamRole
    # List of GlueS3Target to add to the targets dict
    s3_targets: Optional[List[GlueS3Target]] = None
    # The Glue database where results are written,
    # such as: arn:aws:daylight:us-east-1::database/sometable/* .
    database_name: Optional[str] = None
    # A description of the new crawler.
    description: Optional[str] = None
    # A list of collection of targets to crawl.
    targets: Optional[Dict[str, List[dict]]] = None
    # A cron expression used to specify the schedule
    # For example, to run something every day at 12:15 UTC,
    # you would specify: cron(15 12 * * ? *) .
    schedule: Optional[str] = None
    # A list of custom classifiers that the user has registered.
    # By default, all built-in classifiers are included in a crawl,
    # but these custom classifiers always override the default classifiers for a given classification.
    classifiers: Optional[List[str]] = None
    # The table prefix used for catalog tables that are created.
    table_prefix: Optional[str] = None
    # The policy for the crawler's update and deletion behavior.
    schema_change_policy: Optional[Dict[str, str]] = None
    # A policy that specifies whether to crawl the entire dataset again,
    # or to crawl only folders that were added since the last crawler run.
    recrawl_policy: Optional[Dict[str, str]] = None
    lineage_configuration: Optional[Dict[str, str]] = None
    lake_formation_configuration: Optional[Dict[str, str]] = None
    # Crawler configuration information. This versioned JSON string
    # allows users to specify aspects of a crawler's behavior.
    configuration: Optional[str] = None
    # The name of the SecurityConfiguration structure to be used by this crawler.
    crawler_security_configuration: Optional[str] = None
    # The tags to use with this crawler request.
    tags: Optional[Dict[str, str]] = None

    # provided by api on create
    creation_time: Optional[str] = None
    last_crawl: Optional[str] = None

    def get_glue_crawler_targets(self) -> Optional[Dict[str, List[dict]]]:
        # start with user provided targets
        crawler_targets: Optional[Dict[str, List[dict]]] = self.targets

        # Add GlueS3Targets to crawler_targets
        if self.s3_targets is not None:
            # create S3Targets dicts using s3_targets
            new_s3_targets_list: List[dict] = []
            for s3_target in self.s3_targets:
                _new_s3_target_path = f"s3://{s3_target.bucket.name}/{s3_target.dir}"
                # start with the only required argument
                _new_s3_target_dict: Dict[str, Any] = {"Path": _new_s3_target_path}
                # add any optional arguments
                if s3_target.exclusions is not None:
                    _new_s3_target_dict["Exclusions"] = s3_target.exclusions
                if s3_target.connection_name is not None:
                    _new_s3_target_dict["ConnectionName"] = s3_target.connection_name
                if s3_target.sample_size is not None:
                    _new_s3_target_dict["SampleSize"] = s3_target.sample_size
                if s3_target.event_queue_arn is not None:
                    _new_s3_target_dict["EventQueueArn"] = s3_target.event_queue_arn
                if s3_target.dlq_event_queue_arn is not None:
                    _new_s3_target_dict["DlqEventQueueArn"] = s3_target.dlq_event_queue_arn

                new_s3_targets_list.append(_new_s3_target_dict)

            # Add new S3Targets to crawler_targets
            if crawler_targets is None:
                crawler_targets = {}
            # logger.debug(f"new_s3_targets_list: {new_s3_targets_list}")
            existing_s3_targets = crawler_targets.get("S3Targets", [])
            # logger.debug(f"existing_s3_targets: {existing_s3_targets}")
            new_s3_targets = existing_s3_targets + new_s3_targets_list
            # logger.debug(f"new_s3_targets: {new_s3_targets}")
            crawler_targets["S3Targets"] = new_s3_targets

        # TODO: add more targets as needed
        logger.debug(f"GlueCrawler targets: {crawler_targets}")
        return crawler_targets

    def _create(self, aws_client: AwsApiClient) -> bool:
        """Creates the GlueCrawler

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        from botocore.exceptions import ClientError

        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")
        try:
            # create a dict of args which are not null, otherwise aws type validation fails
            not_null_args: Dict[str, Any] = {}
            if self.database_name:
                not_null_args["DatabaseName"] = self.database_name
            if self.description:
                not_null_args["Description"] = self.description
            if self.schedule:
                not_null_args["Schedule"] = self.schedule
            if self.classifiers:
                not_null_args["Classifiers"] = self.classifiers
            if self.table_prefix:
                not_null_args["TablePrefix"] = self.table_prefix
            if self.schema_change_policy:
                not_null_args["SchemaChangePolicy"] = self.schema_change_policy
            if self.recrawl_policy:
                not_null_args["RecrawlPolicy"] = self.recrawl_policy
            if self.lineage_configuration:
                not_null_args["LineageConfiguration"] = self.lineage_configuration
            if self.lake_formation_configuration:
                not_null_args["LakeFormationConfiguration"] = self.lake_formation_configuration
            if self.configuration:
                not_null_args["Configuration"] = self.configuration
            if self.crawler_security_configuration:
                not_null_args["CrawlerSecurityConfiguration"] = self.crawler_security_configuration
            if self.tags:
                not_null_args["Tags"] = self.tags

            targets = self.get_glue_crawler_targets()
            if targets:
                not_null_args["Targets"] = targets

            # Create crawler
            # Get the service_client
            service_client = self.get_service_client(aws_client)
            iam_role_arn = self.iam_role.get_arn(aws_client)
            if iam_role_arn is None:
                logger.error("IamRole ARN unavailable.")
                return False
            create_response = service_client.create_crawler(
                Name=self.name,
                Role=iam_role_arn,
                **not_null_args,
            )
            logger.debug(f"GlueCrawler: {create_response}")
            logger.debug(f"GlueCrawler type: {type(create_response)}")

            if create_response is not None:
                print_info(f"GlueCrawler created: {self.name}")
                self.active_resource = create_response
                return True
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def _read(self, aws_client: AwsApiClient) -> Optional[Any]:
        """Returns the GlueCrawler

        Args:
            aws_client: The AwsApiClient for the current cluster
        """
        from botocore.exceptions import ClientError

        logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")
        try:
            service_client = self.get_service_client(aws_client)
            get_crawler_response = service_client.get_crawler(Name=self.name)
            # logger.debug(f"GlueCrawler: {get_crawler_response}")
            # logger.debug(f"GlueCrawler type: {type(get_crawler_response)}")

            self.creation_time = get_crawler_response.get("Crawler", {}).get("CreationTime", None)
            self.last_crawl = get_crawler_response.get("Crawler", {}).get("LastCrawl", None)
            logger.debug(f"GlueCrawler creation_time: {self.creation_time}")
            logger.debug(f"GlueCrawler last_crawl: {self.last_crawl}")
            if self.creation_time is not None:
                logger.debug(f"GlueCrawler found: {self.name}")
                self.active_resource = get_crawler_response
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return self.active_resource

    def _delete(self, aws_client: AwsApiClient) -> bool:
        """Deletes the GlueCrawler

        Args:
            aws_client: The AwsApiClient for the current cluster
        """

        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")
        try:
            # Delete the GlueCrawler
            service_client = self.get_service_client(aws_client)
            self.active_resource = None
            service_client.delete_crawler(Name=self.name)
            # logger.debug(f"GlueCrawler: {delete_crawler_response}")
            # logger.debug(f"GlueCrawler type: {type(delete_crawler_response)}")
            print_info(f"GlueCrawler deleted: {self.name}")
            return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be deleted.")
            logger.error("Please try again or delete resources manually.")
            logger.error(e)
        return False

    def start_crawler(self, aws_client: Optional[AwsApiClient] = None) -> bool:
        """Runs the GlueCrawler

        Args:
            aws_client: The AwsApiClient for the current cluster
        """

        print_info(f"Starting {self.get_resource_type()}: {self.get_resource_name()}")
        try:
            # Get the service_client
            client: AwsApiClient = aws_client or self.get_aws_client()
            service_client = self.get_service_client(client)
            # logger.debug(f"ServiceClient: {service_client}")
            # logger.debug(f"ServiceClient type: {type(service_client)}")

            try:
                start_crawler_response = service_client.start_crawler(Name=self.name)
                # logger.debug(f"start_crawler_response: {start_crawler_response}")
            except service_client.exceptions.CrawlerRunningException:
                # reference: https://github.com/boto/boto3/issues/1606
                print_info(f"{self.get_resource_type()}: {self.get_resource_name()} already running")
                return True

            if start_crawler_response is not None:
                print_info(f"{self.get_resource_type()}: {self.get_resource_name()} started")
                return True

        except Exception as e:
            logger.error("GlueCrawler could not be started")
            logger.error(e)
            logger.exception(e)
        return False
