import time
from dataclasses import asdict
from decimal import Decimal
from typing import Any, Dict, List, Optional

from agno.storage.agent.base import AgentStorage
from agno.storage.agent.session import AgentSession
from agno.utils.log import logger

try:
    import boto3
    from boto3.dynamodb.conditions import Key
    from botocore.exceptions import ClientError
except ImportError:
    raise ImportError("`boto3` not installed. Please install using `pip install boto3`.")


class DynamoDbAgentStorage(AgentStorage):
    def __init__(
        self,
        table_name: str,
        region_name: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        create_table_if_not_exists: bool = True,
    ):
        """
        Initialize the DynamoDbAgentStorage.

        Args:
            table_name (str): The name of the DynamoDB table.
            region_name (Optional[str]): AWS region name.
            aws_access_key_id (Optional[str]): AWS access key ID.
            aws_secret_access_key (Optional[str]): AWS secret access key.
            endpoint_url (Optional[str]): The complete URL to use for the constructed client.
            create_table_if_not_exists (bool): Whether to create the table if it does not exist.
        """
        self.table_name = table_name
        self.region_name = region_name
        self.endpoint_url = endpoint_url
        self.aws_access_key_id = aws_access_key_id
        self.aws_secret_access_key = aws_secret_access_key
        self.create_table_if_not_exists = create_table_if_not_exists

        # Initialize DynamoDB resource
        self.dynamodb = boto3.resource(
            "dynamodb",
            region_name=self.region_name,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            endpoint_url=self.endpoint_url,
        )

        # Initialize table
        self.table = self.dynamodb.Table(self.table_name)

        # Optionally create table if it does not exist
        if self.create_table_if_not_exists:
            self.create()
        logger.debug(f"Initialized DynamoDbAgentStorage with table '{self.table_name}'")

    def create(self) -> None:
        """
        Create the DynamoDB table if it does not exist.
        """
        try:
            # Check if table exists
            self.dynamodb.meta.client.describe_table(TableName=self.table_name)
            logger.debug(f"Table '{self.table_name}' already exists.")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                logger.debug(f"Creating table '{self.table_name}'.")
                # Create the table
                self.table = self.dynamodb.create_table(
                    TableName=self.table_name,
                    KeySchema=[{"AttributeName": "session_id", "KeyType": "HASH"}],
                    AttributeDefinitions=[
                        {"AttributeName": "session_id", "AttributeType": "S"},
                        {"AttributeName": "user_id", "AttributeType": "S"},
                        {"AttributeName": "agent_id", "AttributeType": "S"},
                        {"AttributeName": "created_at", "AttributeType": "N"},
                    ],
                    GlobalSecondaryIndexes=[
                        {
                            "IndexName": "user_id-index",
                            "KeySchema": [
                                {"AttributeName": "user_id", "KeyType": "HASH"},
                                {"AttributeName": "created_at", "KeyType": "RANGE"},
                            ],
                            "Projection": {"ProjectionType": "ALL"},
                            "ProvisionedThroughput": {
                                "ReadCapacityUnits": 5,
                                "WriteCapacityUnits": 5,
                            },
                        },
                        {
                            "IndexName": "agent_id-index",
                            "KeySchema": [
                                {"AttributeName": "agent_id", "KeyType": "HASH"},
                                {"AttributeName": "created_at", "KeyType": "RANGE"},
                            ],
                            "Projection": {"ProjectionType": "ALL"},
                            "ProvisionedThroughput": {
                                "ReadCapacityUnits": 5,
                                "WriteCapacityUnits": 5,
                            },
                        },
                    ],
                    ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
                )
                # Wait until the table exists.
                self.table.wait_until_exists()
                logger.debug(f"Table '{self.table_name}' created successfully.")
            else:
                logger.error(f"Unable to create table '{self.table_name}': {e.response['Error']['Message']}")
        except Exception as e:
            logger.error(f"Exception during table creation: {e}")

    def read(self, session_id: str, user_id: Optional[str] = None) -> Optional[AgentSession]:
        """
        Read and return an AgentSession from the database.

        Args:
            session_id (str): ID of the session to read.
            user_id (Optional[str]): User ID to filter by. Defaults to None.

        Returns:
            Optional[AgentSession]: AgentSession object if found, None otherwise.
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
                return AgentSession.from_dict(item)
        except Exception as e:
            logger.error(f"Error reading session_id '{session_id}' with user_id '{user_id}': {e}")
        return None

    def get_all_session_ids(self, user_id: Optional[str] = None, agent_id: Optional[str] = None) -> List[str]:
        """
        Retrieve all session IDs, optionally filtered by user_id and/or agent_id.

        Args:
            user_id (Optional[str], optional): User ID to filter by. Defaults to None.
            agent_id (Optional[str], optional): Agent ID to filter by. Defaults to None.

        Returns:
            List[str]: List of session IDs matching the criteria.
        """
        session_ids: List[str] = []
        try:
            if user_id is not None:
                # Query using user_id index
                response = self.table.query(
                    IndexName="user_id-index",
                    KeyConditionExpression=Key("user_id").eq(user_id),
                    ProjectionExpression="session_id",
                )
                items = response.get("Items", [])
                session_ids.extend([item["session_id"] for item in items if "session_id" in item])
            elif agent_id is not None:
                # Query using agent_id index
                response = self.table.query(
                    IndexName="agent_id-index",
                    KeyConditionExpression=Key("agent_id").eq(agent_id),
                    ProjectionExpression="session_id",
                )
                items = response.get("Items", [])
                session_ids.extend([item["session_id"] for item in items if "session_id" in item])
            else:
                # Scan the whole table
                response = self.table.scan(ProjectionExpression="session_id")
                items = response.get("Items", [])
                session_ids.extend([item["session_id"] for item in items if "session_id" in item])
        except Exception as e:
            logger.error(f"Error retrieving session IDs: {e}")
        return session_ids

    def get_all_sessions(self, user_id: Optional[str] = None, agent_id: Optional[str] = None) -> List[AgentSession]:
        """
        Retrieve all sessions, optionally filtered by user_id and/or agent_id.

        Args:
            user_id (Optional[str], optional): User ID to filter by. Defaults to None.
            agent_id (Optional[str], optional): Agent ID to filter by. Defaults to None.

        Returns:
            List[AgentSession]: List of AgentSession objects matching the criteria.
        """
        sessions: List[AgentSession] = []
        try:
            if user_id is not None:
                # Query using user_id index
                response = self.table.query(
                    IndexName="user_id-index",
                    KeyConditionExpression=Key("user_id").eq(user_id),
                    ProjectionExpression="session_id, agent_id, user_id, memory, agent_data, session_data, extra_data, created_at, updated_at",
                )
                items = response.get("Items", [])
                for item in items:
                    item = self._deserialize_item(item)
                    _agent_session = AgentSession.from_dict(item)
                    if _agent_session is not None:
                        sessions.append(_agent_session)
            elif agent_id is not None:
                # Query using agent_id index
                response = self.table.query(
                    IndexName="agent_id-index",
                    KeyConditionExpression=Key("agent_id").eq(agent_id),
                    ProjectionExpression="session_id, agent_id, user_id, memory, agent_data, session_data, extra_data, created_at, updated_at",
                )
                items = response.get("Items", [])
                for item in items:
                    item = self._deserialize_item(item)
                    _agent_session = AgentSession.from_dict(item)
                    if _agent_session is not None:
                        sessions.append(_agent_session)
            else:
                # Scan the whole table
                response = self.table.scan(
                    ProjectionExpression="session_id, agent_id, user_id, memory, agent_data, session_data, extra_data, created_at, updated_at"
                )
                items = response.get("Items", [])
                for item in items:
                    item = self._deserialize_item(item)
                    _agent_session = AgentSession.from_dict(item)
                    if _agent_session is not None:
                        sessions.append(_agent_session)
        except Exception as e:
            logger.error(f"Error retrieving sessions: {e}")
        return sessions

    def upsert(self, session: AgentSession) -> Optional[AgentSession]:
        """
        Create or update an AgentSession in the database.

        Args:
            session (AgentSession): The session data to upsert.

        Returns:
            Optional[AgentSession]: The upserted AgentSession, or None if operation failed.
        """
        try:
            item = asdict(session)

            # Add timestamps
            current_time = int(time.time())
            if "created_at" not in item or item["created_at"] is None:
                item["created_at"] = current_time
            item["updated_at"] = current_time

            # Convert data to DynamoDB compatible format
            item = self._serialize_item(item)

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
            logger.info(f"Successfully deleted session with session_id: {session_id}")
        except Exception as e:
            logger.error(f"Error deleting session: {e}")

    def drop(self) -> None:
        """
        Drop the table from the database if it exists.
        """
        try:
            self.table.delete()
            self.table.wait_until_not_exists()
            logger.debug(f"Table '{self.table_name}' deleted successfully.")
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
        Deserialize item from DynamoDB format.

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
                return {k: deserialize_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [deserialize_value(v) for v in value]
            else:
                return value

        return {k: deserialize_value(v) for k, v in item.items()}
