import time
import json
import gzip
import base64
from dataclasses import asdict
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

from agno.storage.base import Storage
from agno.storage.session import Session
from agno.storage.session.agent import AgentSession
from agno.storage.session.team import TeamSession
from agno.storage.session.v2.workflow import WorkflowSession as WorkflowSessionV2
from agno.storage.session.workflow import WorkflowSession
from agno.utils.log import log_debug, log_info, logger

try:
    import boto3
    from boto3.dynamodb.conditions import Key
    from botocore.exceptions import ClientError
except ImportError:
    raise ImportError("`boto3` not installed. Please install using `pip install boto3`.")


class DynamoDbStorage(Storage):
    def __init__(
        self,
        table_name: str,
        profile_name: Optional[str] = None,
        region_name: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        create_table_if_not_exists: bool = True,
        mode: Optional[Literal["agent", "team", "workflow", "workflow_v2"]] = "agent",
        create_table_read_capacity_units: int = 5,
        create_table_write_capacity_units: int = 5,
    ):
        """
        Initialize the DynamoDbStorage.

        Args:
            table_name (str): The name of the DynamoDB table.
            profile_name (Optional[str]): AWS profile name to use for credentials.
            region_name (Optional[str]): AWS region name.
            aws_access_key_id (Optional[str]): AWS access key ID.
            aws_secret_access_key (Optional[str]): AWS secret access key.
            endpoint_url (Optional[str]): The complete URL to use for the constructed client.
            create_table_if_not_exists (bool): Whether to create the table if it does not exist.
            mode (Optional[Literal["agent", "team", "workflow", "workflow_v2"]]): The mode of the storage.
            create_table_read_capacity_units Optional[int]: Read capacity units for created table (default: 5).
            create_table_write_capacity_units Optional[int]: Write capacity units for created table (default: 5).
        """
        super().__init__(mode)
        self.table_name = table_name
        self.profile_name = profile_name
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.create_table_if_not_exists = create_table_if_not_exists
        self.create_table_read_capacity_units = create_table_read_capacity_units
        self.create_table_write_capacity_units = create_table_write_capacity_units

        # Create session using profile name if provided
        if self.profile_name:
            session = boto3.Session(profile_name=self.profile_name)
            self.dynamodb = session.resource(
                "dynamodb",
                region_name=self.region_name,
                endpoint_url=self.endpoint_url,
            )
        else:
            # Initialize DynamoDB resource with default credentials
            self.dynamodb = boto3.resource(
                "dynamodb",
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                region_name=self.region_name,
                endpoint_url=self.endpoint_url,
            )

        # Initialize table
        self.table = self.dynamodb.Table(self.table_name)

        # Optionally create table if it does not exist
        if self.create_table_if_not_exists:
            self.create()
        log_debug(f"Initialized DynamoDbStorage with table '{self.table_name}'")

    @property
    def mode(self) -> Literal["agent", "team", "workflow", "workflow_v2"]:
        """Get the mode of the storage."""
        return super().mode

    @mode.setter
    def mode(self, value: Optional[Literal["agent", "team", "workflow", "workflow_v2"]]) -> None:
        """Set the mode and refresh the table if mode changes."""
        super(DynamoDbStorage, type(self)).mode.fset(self, value)  # type: ignore
        if value is not None:
            if self.create_table_if_not_exists:
                self.create()

    def create(self) -> None:
        """
        Create the DynamoDB table if it does not exist.
        """
        provisioned_throughput = {
            "ReadCapacityUnits": self.create_table_read_capacity_units,
            "WriteCapacityUnits": self.create_table_write_capacity_units,
        }

        try:
            # Check if table exists
            self.dynamodb.meta.client.describe_table(TableName=self.table_name)
            log_debug(f"Table '{self.table_name}' already exists.")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                log_debug(f"Creating table '{self.table_name}'.")

                attribute_definitions = []
                if self.mode == "agent":
                    attribute_definitions = [
                        {"AttributeName": "session_id", "AttributeType": "S"},
                        {"AttributeName": "user_id", "AttributeType": "S"},
                        {"AttributeName": "agent_id", "AttributeType": "S"},
                        {"AttributeName": "created_at", "AttributeType": "N"},
                    ]
                elif self.mode == "team":
                    attribute_definitions = [
                        {"AttributeName": "session_id", "AttributeType": "S"},
                        {"AttributeName": "user_id", "AttributeType": "S"},
                        {"AttributeName": "team_id", "AttributeType": "S"},
                        {"AttributeName": "created_at", "AttributeType": "N"},
                    ]
                elif self.mode == "workflow":
                    attribute_definitions = [
                        {"AttributeName": "session_id", "AttributeType": "S"},
                        {"AttributeName": "user_id", "AttributeType": "S"},
                        {"AttributeName": "workflow_id", "AttributeType": "S"},
                        {"AttributeName": "created_at", "AttributeType": "N"},
                    ]
                elif self.mode == "workflow_v2":
                    attribute_definitions = [
                        {"AttributeName": "session_id", "AttributeType": "S"},
                        {"AttributeName": "user_id", "AttributeType": "S"},
                        {"AttributeName": "workflow_id", "AttributeType": "S"},
                        {"AttributeName": "created_at", "AttributeType": "N"},
                    ]
                secondary_indexes = [
                    {
                        "IndexName": "user_id-index",
                        "KeySchema": [
                            {"AttributeName": "user_id", "KeyType": "HASH"},
                            {"AttributeName": "created_at", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                        "ProvisionedThroughput": provisioned_throughput,
                    }
                ]
                if self.mode == "agent":
                    secondary_indexes.append(
                        {
                            "IndexName": "agent_id-index",
                            "KeySchema": [
                                {"AttributeName": "agent_id", "KeyType": "HASH"},
                                {"AttributeName": "created_at", "KeyType": "RANGE"},
                            ],
                            "Projection": {"ProjectionType": "ALL"},
                            "ProvisionedThroughput": provisioned_throughput,
                        }
                    )
                elif self.mode == "team":
                    secondary_indexes.append(
                        {
                            "IndexName": "team_id-index",
                            "KeySchema": [
                                {"AttributeName": "team_id", "KeyType": "HASH"},
                                {"AttributeName": "created_at", "KeyType": "RANGE"},
                            ],
                            "Projection": {"ProjectionType": "ALL"},
                            "ProvisionedThroughput": provisioned_throughput,
                        }
                    )
                elif self.mode == "workflow":
                    secondary_indexes.append(
                        {
                            "IndexName": "workflow_id-index",
                            "KeySchema": [
                                {"AttributeName": "workflow_id", "KeyType": "HASH"},
                                {"AttributeName": "created_at", "KeyType": "RANGE"},
                            ],
                            "Projection": {"ProjectionType": "ALL"},
                            "ProvisionedThroughput": provisioned_throughput,
                        }
                    )
                elif self.mode == "workflow_v2":
                    secondary_indexes.append(
                        {
                            "IndexName": "workflow_id-index",
                            "KeySchema": [
                                {"AttributeName": "workflow_id", "KeyType": "HASH"},
                                {"AttributeName": "created_at", "KeyType": "RANGE"},
                            ],
                            "Projection": {"ProjectionType": "ALL"},
                            "ProvisionedThroughput": provisioned_throughput,
                        }
                    )
                # Create the table
                self.table = self.dynamodb.create_table(
                    TableName=self.table_name,
                    KeySchema=[{"AttributeName": "session_id", "KeyType": "HASH"}],
                    AttributeDefinitions=attribute_definitions,
                    GlobalSecondaryIndexes=secondary_indexes,
                    ProvisionedThroughput=provisioned_throughput,
                )
                # Wait until the table exists.
                self.table.wait_until_exists()
                log_debug(f"Table '{self.table_name}' created successfully.")
            else:
                logger.error(f"Unable to create table '{self.table_name}': {e.response['Error']['Message']}")
        except Exception as e:
            logger.error(f"Exception during table creation: {e}")

    def read(self, session_id: str, user_id: Optional[str] = None) -> Optional[Session]:
        """
        Read and return a Session from the database.

        Args:
            session_id (str): ID of the session to read.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Returns:
            Optional[Session]: Session object if found, None otherwise.
        """
        try:
            key = {"session_id": session_id}
            if user_id is not None:
                key["user_id"] = user_id

            response = self.table.get_item(Key=key)
            item = response.get("Item", None)
            if item is not None:
                # Convert Decimal to int or float
                item = self._deserialize_item(item)
                if self.mode == "agent":
                    return AgentSession.from_dict(item)
                elif self.mode == "team":
                    return TeamSession.from_dict(item)
                elif self.mode == "workflow":
                    return WorkflowSession.from_dict(item)
                elif self.mode == "workflow_v2":
                    return WorkflowSessionV2.from_dict(item)
        except Exception as e:
            logger.error(f"Error reading session_id '{session_id}' with user_id '{user_id}': {e}")
        return None

    def get_all_session_ids(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[str]:
        """
        Retrieve all session IDs, optionally filtered by user_id and/or entity_id.

        Args:
            user_id (Optional[str], optional): User ID to filter by. Defaults to None.
            entity_id (Optional[str], optional): Entity ID to filter by. Defaults to None.

        Returns:
            List[str]: List of session IDs matching the criteria.
        """
        session_ids: List[str] = []
        try:
            if user_id is not None:
                # Query using user_id index with pagination
                query_kwargs = {
                    "IndexName": "user_id-index",
                    "KeyConditionExpression": Key("user_id").eq(user_id),
                    "ProjectionExpression": "session_id",
                }
                while True:
                    response = self.table.query(**query_kwargs)
                    items = response.get("Items", [])
                    session_ids.extend([item["session_id"] for item in items if "session_id" in item])

                    last_evaluated_key = response.get("LastEvaluatedKey")
                    if not last_evaluated_key:
                        break
                    query_kwargs["ExclusiveStartKey"] = last_evaluated_key

            elif entity_id is not None:
                # Query using entity_id index with pagination
                query_kwargs = {"ProjectionExpression": "session_id"}
                if self.mode == "agent":
                    query_kwargs["IndexName"] = "agent_id-index"
                    query_kwargs["KeyConditionExpression"] = Key("agent_id").eq(entity_id)
                elif self.mode == "team":
                    query_kwargs["IndexName"] = "team_id-index"
                    query_kwargs["KeyConditionExpression"] = Key("team_id").eq(entity_id)
                elif self.mode == "workflow":
                    query_kwargs["IndexName"] = "workflow_id-index"
                    query_kwargs["KeyConditionExpression"] = Key("workflow_id").eq(entity_id)

                while True:
                    response = self.table.query(**query_kwargs)
                    items = response.get("Items", [])
                    session_ids.extend([item["session_id"] for item in items if "session_id" in item])

                    last_evaluated_key = response.get("LastEvaluatedKey")
                    if not last_evaluated_key:
                        break
                    query_kwargs["ExclusiveStartKey"] = last_evaluated_key

            else:
                # Scan the whole table with pagination
                scan_kwargs = {"ProjectionExpression": "session_id"}
                while True:
                    response = self.table.scan(**scan_kwargs)
                    items = response.get("Items", [])
                    session_ids.extend([item["session_id"] for item in items if "session_id" in item])

                    last_evaluated_key = response.get("LastEvaluatedKey")
                    if not last_evaluated_key:
                        break
                    scan_kwargs["ExclusiveStartKey"] = last_evaluated_key

        except Exception as e:
            logger.error(f"Error retrieving session IDs: {e}")
        return session_ids

    def get_all_sessions(self, user_id: Optional[str] = None, entity_id: Optional[str] = None) -> List[Session]:
        """
        Retrieve all sessions, optionally filtered by user_id and/or entity_id.

        Args:
            user_id (Optional[str], optional): User ID to filter by. Defaults to None.
            entity_id (Optional[str], optional): Entity ID to filter by. Defaults to None.

        Returns:
            List[Session]: List of AgentSession or WorkflowSession objects matching the criteria.
        """
        sessions: List[Session] = []
        try:
            query_kwargs = {}
            if user_id is not None:
                if self.mode == "agent":
                    query_kwargs = {
                        "IndexName": "user_id-index",
                        "KeyConditionExpression": Key("user_id").eq(user_id),
                        "ProjectionExpression": "session_id, agent_id, user_id, team_session_id, memory, agent_data, session_data, extra_data, created_at, updated_at",
                    }
                elif self.mode == "team":
                    query_kwargs = {
                        "IndexName": "user_id-index",
                        "KeyConditionExpression": Key("user_id").eq(user_id),
                        "ProjectionExpression": "session_id, team_id, user_id, team_session_id, memory, team_data, session_data, extra_data, created_at, updated_at",
                    }
                elif self.mode == "workflow":
                    query_kwargs = {
                        "IndexName": "user_id-index",
                        "KeyConditionExpression": Key("user_id").eq(user_id),
                        "ProjectionExpression": "session_id, workflow_id, user_id, memory, workflow_data, session_data, extra_data, created_at, updated_at",
                    }
                elif self.mode == "workflow_v2":
                    # Query using user_id index
                    query_kwargs = {
                        "IndexName": "user_id-index",
                        "KeyConditionExpression": Key("user_id").eq(user_id),
                        "ProjectionExpression": "session_id, workflow_id, user_id, workflow_name, runs, workflow_data, session_data, extra_data, created_at, updated_at",
                    }
            elif entity_id is not None:
                if self.mode == "agent":
                    query_kwargs = {
                        "IndexName": "agent_id-index",
                        "KeyConditionExpression": Key("agent_id").eq(entity_id),
                        "ProjectionExpression": "session_id, agent_id, user_id, team_session_id, memory, agent_data, session_data, extra_data, created_at, updated_at",
                    }
                elif self.mode == "team":
                    query_kwargs = {
                        "IndexName": "team_id-index",
                        "KeyConditionExpression": Key("team_id").eq(entity_id),
                        "ProjectionExpression": "session_id, team_id, user_id, team_session_id, memory, team_data, session_data, extra_data, created_at, updated_at",
                    }
                elif self.mode == "workflow":
                    query_kwargs = {
                        "IndexName": "workflow_id-index",
                        "KeyConditionExpression": Key("workflow_id").eq(entity_id),
                        "ProjectionExpression": "session_id, workflow_id, user_id, memory, workflow_data, session_data, extra_data, created_at, updated_at",
                    }
            else:
                # This case will scan the entire table, which can be slow and costly.
                # It's generally better to query with a specific index.
                logger.warning("Scanning the entire table without a filter.")
                scan_kwargs = {}
                while True:
                    response = self.table.scan(**scan_kwargs)
                    items = response.get("Items", [])
                    for item in items:
                        deserialized_item = self._deserialize_item(item)
                        if self.mode == "agent":
                            sessions.append(AgentSession.from_dict(deserialized_item))
                        elif self.mode == "team":
                            sessions.append(TeamSession.from_dict(deserialized_item))
                        elif self.mode == "workflow":
                            sessions.append(WorkflowSession.from_dict(deserialized_item))

                    last_evaluated_key = response.get("LastEvaluatedKey")
                    if not last_evaluated_key:
                        break
                    scan_kwargs["ExclusiveStartKey"] = last_evaluated_key
                return sessions

            # Common query execution with pagination
            while True:
                response = self.table.query(**query_kwargs)
                items = response.get("Items", [])
                for item in items:
                    deserialized_item = self._deserialize_item(item)
                    if self.mode == "agent":
                        sessions.append(AgentSession.from_dict(deserialized_item))
                    elif self.mode == "team":
                        sessions.append(TeamSession.from_dict(deserialized_item))
                    elif self.mode == "workflow":
                        sessions.append(WorkflowSession.from_dict(deserialized_item))

                last_evaluated_key = response.get("LastEvaluatedKey")
                if not last_evaluated_key:
                    break
                query_kwargs["ExclusiveStartKey"] = last_evaluated_key

        except Exception as e:
            logger.error(f"Error retrieving sessions: {e}")
        return sessions

    def get_recent_sessions(
        self,
        user_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        limit: Optional[int] = 2,
    ) -> List[Session]:
        """Get the last N sessions, ordered by created_at descending.

        Args:
            num_history_sessions: Number of most recent sessions to return
            user_id: Filter by user ID
            entity_id: Filter by entity ID (agent_id, team_id, or workflow_id)

        Returns:
            List[Session]: List of most recent sessions
        """
        sessions: List[Session] = []
        try:
            if user_id is not None:
                if self.mode == "agent":
                    response = self.table.query(
                        IndexName="user_id-index",
                        KeyConditionExpression=Key("user_id").eq(user_id),
                        ProjectionExpression="session_id, agent_id, user_id, team_session_id, memory, agent_data, session_data, extra_data, created_at, updated_at",
                        ScanIndexForward=False,
                        Limit=limit if limit is not None else None,
                    )
                elif self.mode == "team":
                    response = self.table.query(
                        IndexName="user_id-index",
                        KeyConditionExpression=Key("user_id").eq(user_id),
                        ProjectionExpression="session_id, team_id, user_id, team_session_id, memory, team_data, session_data, extra_data, created_at, updated_at",
                        ScanIndexForward=False,
                        Limit=limit if limit is not None else None,
                    )
                elif self.mode == "workflow":
                    response = self.table.query(
                        IndexName="user_id-index",
                        KeyConditionExpression=Key("user_id").eq(user_id),
                        ProjectionExpression="session_id, workflow_id, user_id, memory, workflow_data, session_data, extra_data, created_at, updated_at",
                        ScanIndexForward=False,
                        Limit=limit if limit is not None else None,
                    )
                elif self.mode == "workflow_v2":
                    response = self.table.query(
                        IndexName="user_id-index",
                        KeyConditionExpression=Key("user_id").eq(user_id),
                        ProjectionExpression="session_id, workflow_id, user_id, workflow_name, runs, workflow_data, session_data, extra_data, created_at, updated_at",
                        ScanIndexForward=False,
                        Limit=limit if limit is not None else None,
                    )
            elif entity_id is not None:
                if self.mode == "agent":
                    response = self.table.query(
                        IndexName="agent_id-index",
                        KeyConditionExpression=Key("agent_id").eq(entity_id),
                        ProjectionExpression="session_id, agent_id, user_id, team_session_id, memory, agent_data, session_data, extra_data, created_at, updated_at",
                        ScanIndexForward=False,
                        Limit=limit if limit is not None else None,
                    )
                elif self.mode == "team":
                    response = self.table.query(
                        IndexName="team_id-index",
                        KeyConditionExpression=Key("team_id").eq(entity_id),
                        ProjectionExpression="session_id, team_id, user_id, team_session_id, memory, team_data, session_data, extra_data, created_at, updated_at",
                        ScanIndexForward=False,
                        Limit=limit if limit is not None else None,
                    )
                elif self.mode == "workflow":
                    response = self.table.query(
                        IndexName="workflow_id-index",
                        KeyConditionExpression=Key("workflow_id").eq(entity_id),
                        ProjectionExpression="session_id, workflow_id, user_id, memory, workflow_data, session_data, extra_data, created_at, updated_at",
                        ScanIndexForward=False,
                        Limit=limit if limit is not None else None,
                    )
                elif self.mode == "workflow_v2":
                    response = self.table.query(
                        IndexName="workflow_id-index",
                        KeyConditionExpression=Key("workflow_id").eq(entity_id),
                        ProjectionExpression="session_id, workflow_id, user_id, workflow_name, runs, workflow_data, session_data, extra_data, created_at, updated_at",
                        ScanIndexForward=False,
                        Limit=limit if limit is not None else None,
                    )
            else:
                # If no filters, scan the table and sort by created_at
                if self.mode == "agent":
                    response = self.table.scan(
                        ProjectionExpression="session_id, agent_id, user_id, team_session_id, memory, agent_data, session_data, extra_data, created_at, updated_at",
                        Limit=limit if limit is not None else None,
                    )
                elif self.mode == "team":
                    response = self.table.scan(
                        ProjectionExpression="session_id, team_id, user_id, team_session_id, memory, team_data, session_data, extra_data, created_at, updated_at",
                        Limit=limit if limit is not None else None,
                    )
                elif self.mode == "workflow":
                    response = self.table.scan(
                        ProjectionExpression="session_id, workflow_id, user_id, memory, workflow_data, session_data, extra_data, created_at, updated_at",
                        Limit=limit if limit is not None else None,
                    )
                elif self.mode == "workflow_v2":
                    response = self.table.scan(
                        ProjectionExpression="session_id, workflow_id, user_id, workflow_name, runs, workflow_data, session_data, extra_data, created_at, updated_at",
                        Limit=limit if limit is not None else None,
                    )
            items = response.get("Items", [])
            for item in items:
                item = self._deserialize_item(item)
                session: Optional[Session] = None

                if self.mode == "agent":
                    session = AgentSession.from_dict(item)
                elif self.mode == "team":
                    session = TeamSession.from_dict(item)
                elif self.mode == "workflow":
                    session = WorkflowSession.from_dict(item)
                elif self.mode == "workflow_v2":
                    session = WorkflowSessionV2.from_dict(item)
                if session is not None:
                    sessions.append(session)

        except Exception as e:
            logger.error(f"Error getting last {limit} sessions: {e}")

        return sessions

    def upsert(self, session: Session) -> Optional[Session]:
        """
        Create or update a Session in the database.
        Handles large items by compressing data that exceeds DynamoDB's 400KB limit.

        Args:
            session (Session): The session data to upsert.

        Returns:
            Optional[Session]: The upserted Session, or None if operation failed.
        """
        try:
            if self.mode == "workflow_v2":
                item = session.to_dict()
            else:
                item = asdict(session)

            # Add timestamps
            current_time = int(time.time())
            if "created_at" not in item or item["created_at"] is None:
                item["created_at"] = current_time
            item["updated_at"] = current_time

            # Convert data to DynamoDB compatible format
            item = self._serialize_item(item)

            # Check item size and compress if necessary
            item = self._handle_large_item(item)

            # Put item into DynamoDB
            self.table.put_item(Item=item)
            return self.read(session.session_id)
        except Exception as e:
            logger.error(f"Error upserting session: {e}")
            return None

    def delete_session(self, session_id: Optional[str] = None):
        """
        Delete a session from the database.

        Args:
            session_id (Optional[str], optional): ID of the session to delete. Defaults to None.
        """
        if session_id is None:
            logger.warning("No session_id provided for deletion.")
            return
        try:
            self.table.delete_item(Key={"session_id": session_id})
            log_info(f"Successfully deleted session with session_id: {session_id}")
        except Exception as e:
            logger.error(f"Error deleting session: {e}")

    def drop(self) -> None:
        """
        Drop the table from the database if it exists.
        """
        try:
            self.table.delete()
            self.table.wait_until_not_exists()
            log_debug(f"Table '{self.table_name}' deleted successfully.")
        except Exception as e:
            logger.error(f"Error deleting table '{self.table_name}': {e}")

    def upgrade_schema(self) -> None:
        """
        Upgrade the schema to the latest version.
        This method is currently a placeholder and does not perform any actions.
        """
        pass

    def _serialize_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Serialize item to be compatible with DynamoDB.

        Args:
            item (Dict[str, Any]): The item to serialize.

        Returns:
            Dict[str, Any]: The serialized item.
        """

        def serialize_value(value):
            if isinstance(value, float):
                return Decimal(str(value))
            elif isinstance(value, dict):
                return {k: serialize_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [serialize_value(v) for v in value]
            else:
                return value

        return {k: serialize_value(v) for k, v in item.items() if v is not None}

    def _deserialize_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Deserialize item from DynamoDB format and decompress compressed fields.

        Args:
            item (Dict[str, Any]): The item to deserialize.

        Returns:
            Dict[str, Any]: The deserialized item.
        """

        def deserialize_value(value):
            if isinstance(value, Decimal):
                if value % 1 == 0:
                    return int(value)
                else:
                    return float(value)
            elif isinstance(value, dict):
                # Check if this is a compressed field
                if value.get("_compressed") is True and "_data" in value:
                    try:
                        # Decompress the data
                        encoded_data = value["_data"]
                        compressed_data = base64.b64decode(encoded_data.encode("utf-8"))
                        decompressed_data = gzip.decompress(compressed_data).decode("utf-8")
                        return json.loads(decompressed_data)
                    except Exception as e:
                        logger.error(f"Failed to decompress field: {e}")
                        # Return empty dict if decompression fails
                        return {}
                else:
                    return {k: deserialize_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [deserialize_value(v) for v in value]
            else:
                return value

        return {k: deserialize_value(v) for k, v in item.items()}

    def _calculate_item_size(self, item: Dict[str, Any]) -> int:
        """
        Calculate the approximate size of a DynamoDB item in bytes.

        Args:
            item (Dict[str, Any]): The item to calculate size for.

        Returns:
            int: Approximate size in bytes.
        """
        return len(json.dumps(item, default=str).encode("utf-8"))

    def _handle_large_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle items that exceed DynamoDB's 400KB limit by compressing large fields.

        Args:
            item (Dict[str, Any]): The item to process.

        Returns:
            Dict[str, Any]: Processed item with compression if needed.
        """
        # DynamoDB limit is 400KB, leave some buffer
        MAX_ITEM_SIZE = 380 * 1024  # 380KB

        current_size = self._calculate_item_size(item)

        if current_size <= MAX_ITEM_SIZE:
            return item

        logger.warning(f"Item size ({current_size} bytes) exceeds limit. Applying compression.")

        # Fields that are typically large and can be compressed
        compressible_fields = ["memory", "agent_data", "team_data", "workflow_data", "session_data", "extra_data"]

        compressed_item = item.copy()

        for field in compressible_fields:
            if field in compressed_item and compressed_item[field]:
                try:
                    # Compress the field
                    field_data = json.dumps(compressed_item[field], default=str)
                    compressed_data = gzip.compress(field_data.encode("utf-8"))
                    encoded_data = base64.b64encode(compressed_data).decode("utf-8")

                    # Replace with compressed version and mark as compressed
                    compressed_item[field] = {
                        "_compressed": True,
                        "_data": encoded_data,
                        "_original_size": len(field_data),
                    }

                    # Check if we're now under the limit
                    new_size = self._calculate_item_size(compressed_item)
                    logger.info(f"Compressed {field}: {len(field_data)} -> {len(encoded_data)} bytes")

                    if new_size <= MAX_ITEM_SIZE:
                        logger.info(f"Item size after compression: {new_size} bytes")
                        return compressed_item

                except Exception as e:
                    logger.error(f"Failed to compress field {field}: {e}")
                    # Restore original field if compression fails
                    compressed_item[field] = item[field]

        # If still too large after compression, truncate memory/history
        final_size = self._calculate_item_size(compressed_item)
        if final_size > MAX_ITEM_SIZE:
            logger.warning(f"Item still too large ({final_size} bytes) after compression. Truncating data.")
            compressed_item = self._truncate_large_fields(compressed_item, MAX_ITEM_SIZE)

        return compressed_item

    def _truncate_large_fields(self, item: Dict[str, Any], max_size: int) -> Dict[str, Any]:
        """
        Truncate large fields to fit within size limit.

        Args:
            item (Dict[str, Any]): The item to truncate.
            max_size (int): Maximum allowed size in bytes.

        Returns:
            Dict[str, Any]: Truncated item.
        """
        truncated_item = item.copy()

        # Truncate memory field if it exists (keep only recent entries)
        if "memory" in truncated_item and isinstance(truncated_item["memory"], dict):
            memory = truncated_item["memory"]
            if isinstance(memory.get("chat_history"), list):
                # Keep only the last 50 messages
                memory["chat_history"] = memory["chat_history"][-50:]
                logger.warning("Truncated chat_history to last 50 messages")

        # Check size after truncation
        current_size = self._calculate_item_size(truncated_item)
        if current_size <= max_size:
            return truncated_item

        # If still too large, remove non-essential fields
        non_essential_fields = ["extra_data", "session_data"]
        for field in non_essential_fields:
            if field in truncated_item:
                del truncated_item[field]
                logger.warning(f"Removed {field} to reduce item size")

                current_size = self._calculate_item_size(truncated_item)
                if current_size <= max_size:
                    return truncated_item

        return truncated_item
