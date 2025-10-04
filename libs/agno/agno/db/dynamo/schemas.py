"""Table schemas and related utils used by the DynamoDb class"""

from typing import Any, Dict

SESSION_TABLE_SCHEMA = {
    "TableName": "agno_sessions",
    "KeySchema": [{"AttributeName": "session_id", "KeyType": "HASH"}],
    "AttributeDefinitions": [
        {"AttributeName": "session_id", "AttributeType": "S"},
        {"AttributeName": "session_type", "AttributeType": "S"},
        {"AttributeName": "user_id", "AttributeType": "S"},
        {"AttributeName": "agent_id", "AttributeType": "S"},
        {"AttributeName": "team_id", "AttributeType": "S"},
        {"AttributeName": "workflow_id", "AttributeType": "S"},
        {"AttributeName": "created_at", "AttributeType": "N"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "session_type-created_at-index",
            "KeySchema": [
                {"AttributeName": "session_type", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
        {
            "IndexName": "user_id-created_at-index",
            "KeySchema": [
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
        {
            "IndexName": "agent_id-created_at-index",
            "KeySchema": [
                {"AttributeName": "agent_id", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
        {
            "IndexName": "team_id-created_at-index",
            "KeySchema": [
                {"AttributeName": "team_id", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
        {
            "IndexName": "workflow_id-created_at-index",
            "KeySchema": [
                {"AttributeName": "workflow_id", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
    ],
    "BillingMode": "PROVISIONED",
    "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
}

USER_MEMORY_TABLE_SCHEMA = {
    "TableName": "agno_user_memory",
    "KeySchema": [{"AttributeName": "memory_id", "KeyType": "HASH"}],
    "AttributeDefinitions": [
        {"AttributeName": "memory_id", "AttributeType": "S"},
        {"AttributeName": "user_id", "AttributeType": "S"},
        {"AttributeName": "agent_id", "AttributeType": "S"},
        {"AttributeName": "team_id", "AttributeType": "S"},
        {"AttributeName": "workflow_id", "AttributeType": "S"},
        {"AttributeName": "updated_at", "AttributeType": "S"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "user_id-updated_at-index",
            "KeySchema": [
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "updated_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
        {
            "IndexName": "agent_id-updated_at-index",
            "KeySchema": [
                {"AttributeName": "agent_id", "KeyType": "HASH"},
                {"AttributeName": "updated_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
        {
            "IndexName": "team_id-updated_at-index",
            "KeySchema": [
                {"AttributeName": "team_id", "KeyType": "HASH"},
                {"AttributeName": "updated_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
        {
            "IndexName": "workflow_id-updated_at-index",
            "KeySchema": [
                {"AttributeName": "workflow_id", "KeyType": "HASH"},
                {"AttributeName": "updated_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
    ],
    "BillingMode": "PROVISIONED",
    "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
}

EVAL_TABLE_SCHEMA = {
    "TableName": "agno_eval",
    "KeySchema": [{"AttributeName": "run_id", "KeyType": "HASH"}],
    "AttributeDefinitions": [
        {"AttributeName": "run_id", "AttributeType": "S"},
        {"AttributeName": "eval_type", "AttributeType": "S"},
        {"AttributeName": "agent_id", "AttributeType": "S"},
        {"AttributeName": "team_id", "AttributeType": "S"},
        {"AttributeName": "workflow_id", "AttributeType": "S"},
        {"AttributeName": "created_at", "AttributeType": "N"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "eval_type-created_at-index",
            "KeySchema": [
                {"AttributeName": "eval_type", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
        {
            "IndexName": "agent_id-created_at-index",
            "KeySchema": [
                {"AttributeName": "agent_id", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
        {
            "IndexName": "team_id-created_at-index",
            "KeySchema": [
                {"AttributeName": "team_id", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
        {
            "IndexName": "workflow_id-created_at-index",
            "KeySchema": [
                {"AttributeName": "workflow_id", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
    ],
    "BillingMode": "PROVISIONED",
    "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
}

KNOWLEDGE_TABLE_SCHEMA = {
    "TableName": "agno_knowledge",
    "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
    "AttributeDefinitions": [
        {"AttributeName": "id", "AttributeType": "S"},
        {"AttributeName": "type", "AttributeType": "S"},
        {"AttributeName": "status", "AttributeType": "S"},
        {"AttributeName": "created_at", "AttributeType": "N"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "user_id-created_at-index",
            "KeySchema": [
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
        {
            "IndexName": "type-created_at-index",
            "KeySchema": [
                {"AttributeName": "type", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
        {
            "IndexName": "status-created_at-index",
            "KeySchema": [
                {"AttributeName": "status", "KeyType": "HASH"},
                {"AttributeName": "created_at", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
    ],
    "BillingMode": "PROVISIONED",
    "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
}

METRICS_TABLE_SCHEMA = {
    "TableName": "agno_metrics",
    "KeySchema": [{"AttributeName": "id", "KeyType": "HASH"}],
    "AttributeDefinitions": [
        {"AttributeName": "id", "AttributeType": "S"},
        {"AttributeName": "date", "AttributeType": "S"},
        {"AttributeName": "aggregation_period", "AttributeType": "S"},
        {"AttributeName": "created_at", "AttributeType": "N"},
    ],
    "GlobalSecondaryIndexes": [
        {
            "IndexName": "date-aggregation_period-index",
            "KeySchema": [
                {"AttributeName": "date", "KeyType": "HASH"},
                {"AttributeName": "aggregation_period", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
        {
            "IndexName": "created_at-index",
            "KeySchema": [{"AttributeName": "created_at", "KeyType": "HASH"}],
            "Projection": {"ProjectionType": "ALL"},
            "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        },
    ],
    "BillingMode": "PROVISIONED",
    "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
}


def get_table_schema_definition(table_type: str) -> Dict[str, Any]:
    """
    Get the expected schema definition for the given table.

    Args:
        table_type (str): The type of table to get the schema for.

    Returns:
        Dict[str, Any]: Dictionary containing DynamoDB table schema definition
    """
    schemas = {
        "sessions": SESSION_TABLE_SCHEMA,
        "memories": USER_MEMORY_TABLE_SCHEMA,
        "evals": EVAL_TABLE_SCHEMA,
        "knowledge": KNOWLEDGE_TABLE_SCHEMA,
        "metrics": METRICS_TABLE_SCHEMA,
    }

    schema = schemas.get(table_type, {})
    if not schema:
        raise ValueError(f"Unknown table type: {table_type}")

    return schema.copy()  # Return a copy to avoid modifying the original schema
