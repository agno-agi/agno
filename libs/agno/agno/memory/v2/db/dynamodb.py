import json
import time
from typing import Any, Dict, List, Optional

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    raise ImportError("`boto3` not installed. Please install it using `pip install boto3`")

from agno.memory.v2.db.base import MemoryDb
from agno.memory.v2.db.schema import MemoryRow
from agno.utils.log import log_debug, log_info, logger


class DynamoDBMemoryDb(MemoryDb):
    def __init__(
        self,
        table_name: str = "agno_memory",
        region_name: str = "us-east-1",
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        endpoint_url: Optional[str] = None,
    ):
        """
        Initialize DynamoDB memory store.

        Args:
            table_name (str): DynamoDB table name
            region_name (str): AWS region name
            aws_access_key_id (Optional[str]): AWS access key ID
            aws_secret_access_key (Optional[str]): AWS secret access key
            endpoint_url (Optional[str]): Custom endpoint URL (for local DynamoDB)
        """
        self.table_name = table_name
        self.region_name = region_name

        # Initialize DynamoDB client
        session_kwargs = {"region_name": region_name}
        if aws_access_key_id and aws_secret_access_key:
            session_kwargs.update(
                {
                    "aws_access_key_id": aws_access_key_id,
                    "aws_secret_access_key": aws_secret_access_key,
                }
            )

        self.session = boto3.Session(**session_kwargs)

        client_kwargs = {}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url

        self.dynamodb = self.session.resource("dynamodb", **client_kwargs)
        self.table = self.dynamodb.Table(table_name)
        self.create()

        log_debug(f"Created DynamoDBMemoryDb with table: '{self.table_name}'")

    def __dict__(self) -> Dict[str, Any]:
        return {
            "name": "DynamoDBMemoryDb",
            "table_name": self.table_name,
            "region_name": self.region_name,
        }

    def create(self) -> None:
        """Create DynamoDB table if it doesn't exist"""
        try:
            # Check if table exists
            if self.table_exists():
                log_debug(f"Table {self.table_name} already exists")
                return

            # Create table
            self.dynamodb.create_table(
                TableName=self.table_name,
                KeySchema=[
                    {"AttributeName": "id", "KeyType": "HASH"}  # Partition key
                ],
                AttributeDefinitions=[
                    {"AttributeName": "id", "AttributeType": "S"},
                    {"AttributeName": "user_id", "AttributeType": "S"},
                ],
                GlobalSecondaryIndexes=[
                    {
                        "IndexName": "user_id-index",
                        "KeySchema": [{"AttributeName": "user_id", "KeyType": "HASH"}],
                        "Projection": {"ProjectionType": "ALL"},
                    }
                ],
                BillingMode="PAY_PER_REQUEST",
            )

            # Wait for table to be created
            self.table.wait_until_exists()
            log_info(f"Created DynamoDB table: {self.table_name}")

        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceInUseException":
                log_debug(f"Table {self.table_name} already exists")
            else:
                logger.error(f"Error creating DynamoDB table: {e}")
                raise

    def memory_exists(self, memory: MemoryRow) -> bool:
        """Check if a memory exists"""
        try:
            response = self.table.get_item(Key={"id": memory.id})
            return "Item" in response
        except ClientError as e:
            logger.error(f"Error checking memory existence: {e}")
            return False

    def read_memories(
        self, user_id: Optional[str] = None, limit: Optional[int] = None, sort: Optional[str] = None
    ) -> List[MemoryRow]:
        """Read memories from DynamoDB"""
        memories: List[MemoryRow] = []
        try:
            if user_id:
                # Query by user_id using GSI
                query_kwargs = {
                    "IndexName": "user_id-index",
                    "KeyConditionExpression": "user_id = :user_id",
                    "ExpressionAttributeValues": {":user_id": user_id},
                }
                if limit:
                    query_kwargs["Limit"] = limit

                response = self.table.query(**query_kwargs)
                items = response.get("Items", [])
            else:
                # Scan entire table
                scan_kwargs = {}
                if limit:
                    scan_kwargs["Limit"] = limit

                response = self.table.scan(**scan_kwargs)
                items = response.get("Items", [])

            # Convert items to MemoryRow objects
            memory_data = []
            for item in items:
                # Convert DynamoDB item to dict format expected by MemoryRow
                memory_dict = {
                    "id": item["id"],
                    "memory": json.loads(item["memory"]) if isinstance(item["memory"], str) else item["memory"],
                    "user_id": item.get("user_id"),
                }

                # Handle timestamps
                if "created_at" in item:
                    memory_dict["created_at"] = item["created_at"]
                if "updated_at" in item:
                    memory_dict["updated_at"] = item["updated_at"]

                memory_data.append(memory_dict)

            # Sort by created_at timestamp
            if sort == "asc":
                memory_data.sort(key=lambda x: x.get("created_at", 0))
            else:
                memory_data.sort(key=lambda x: x.get("created_at", 0), reverse=True)

            # Apply limit if not already applied and needed
            if limit is not None and limit > 0 and not user_id:
                memory_data = memory_data[:limit]

            # Convert to MemoryRow objects
            for data in memory_data:
                memories.append(MemoryRow.model_validate(data))

        except ClientError as e:
            logger.error(f"Error reading memories: {e}")

        return memories

    def upsert_memory(self, memory: MemoryRow) -> Optional[MemoryRow]:
        """Upsert a memory in DynamoDB"""
        try:
            timestamp = int(time.time())

            # Prepare item for DynamoDB
            item = {
                "id": memory.id,
                "memory": json.dumps(memory.memory),
                "updated_at": timestamp,
            }

            if memory.user_id:
                item["user_id"] = memory.user_id

            # Add created_at if this is a new item
            try:
                existing = self.table.get_item(Key={"id": memory.id})
                if "Item" not in existing:
                    item["created_at"] = timestamp
                else:
                    # Preserve original created_at
                    item["created_at"] = existing["Item"].get("created_at", timestamp)
            except ClientError:
                item["created_at"] = timestamp

            # Put item in DynamoDB
            self.table.put_item(Item=item)
            return memory

        except ClientError as e:
            logger.error(f"Error upserting memory: {e}")
            return None

    def delete_memory(self, memory_id: str) -> None:
        """Delete a memory from DynamoDB"""
        try:
            self.table.delete_item(Key={"id": memory_id})
            log_debug(f"Deleted memory: {memory_id}")
        except ClientError as e:
            logger.error(f"Error deleting memory: {e}")

    def drop_table(self) -> None:
        """Drop the DynamoDB table"""
        try:
            self.table.delete()
            self.table.wait_until_not_exists()
            log_info(f"Dropped DynamoDB table: {self.table_name}")
        except ClientError as e:
            logger.error(f"Error dropping table: {e}")

    def table_exists(self) -> bool:
        """Check if the DynamoDB table exists"""
        try:
            self.table.load()
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                return False
            logger.error(f"Error checking if table exists: {e}")
            return False

    def clear(self) -> bool:
        """Clear all memories from the table"""
        try:
            # Scan all items to get their keys
            response = self.table.scan(ProjectionExpression="id")
            items = response.get("Items", [])

            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.table.scan(ProjectionExpression="id", ExclusiveStartKey=response["LastEvaluatedKey"])
                items.extend(response.get("Items", []))

            # Delete items in batches
            deleted_count = 0
            with self.table.batch_writer() as batch:
                for item in items:
                    batch.delete_item(Key={"id": item["id"]})
                    deleted_count += 1

            log_info(f"Cleared {deleted_count} memories from table: {self.table_name}")
            return True

        except ClientError as e:
            logger.error(f"Error clearing memories: {e}")
            return False
