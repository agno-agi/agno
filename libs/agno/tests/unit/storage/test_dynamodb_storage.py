from unittest.mock import MagicMock, patch

import pytest
from boto3.dynamodb.conditions import Key

from agno.storage.dynamodb import DynamoDbStorage
from agno.storage.session.agent import AgentSession
from agno.storage.session.workflow import WorkflowSession


@pytest.fixture
def mock_dynamodb_resource():
    """Create a mock boto3 DynamoDB resource."""
    with patch("agno.storage.dynamodb.boto3.resource") as mock_resource:
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table
        yield mock_resource, mock_table


@pytest.fixture
def agent_storage(mock_dynamodb_resource):
    """Create a DynamoDbStorage instance for agent mode with mocked components."""
    mock_resource, mock_table = mock_dynamodb_resource

    # Mock table.wait_until_exists to avoid actual waiting
    mock_table.wait_until_exists = MagicMock()

    # Create storage with create_table_if_not_exists=False to avoid table creation
    storage = DynamoDbStorage(
        table_name="agent_sessions", region_name="us-east-1", create_table_if_not_exists=False, mode="agent"
    )

    return storage, mock_table


@pytest.fixture
def workflow_storage(mock_dynamodb_resource):
    """Create a DynamoDbStorage instance for workflow mode with mocked components."""
    mock_resource, mock_table = mock_dynamodb_resource

    # Mock table.wait_until_exists to avoid actual waiting
    mock_table.wait_until_exists = MagicMock()

    # Create storage with create_table_if_not_exists=False to avoid table creation
    storage = DynamoDbStorage(
        table_name="workflow_sessions", region_name="us-east-1", create_table_if_not_exists=False, mode="workflow"
    )

    return storage, mock_table


def test_initialization():
    """Test DynamoDbStorage initialization with different parameters."""
    # Test with region_name
    with patch("agno.storage.dynamodb.boto3.resource") as mock_resource:
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table
        mock_table.wait_until_exists = MagicMock()

        storage = DynamoDbStorage(table_name="test_table", region_name="us-west-2", create_table_if_not_exists=False)

        mock_resource.assert_called_once_with(
            "dynamodb", region_name="us-west-2", aws_access_key_id=None, aws_secret_access_key=None, endpoint_url=None
        )
        assert storage.table_name == "test_table"
        assert storage.mode == "agent"  # Default value

    # Test with credentials
    with patch("agno.storage.dynamodb.boto3.resource") as mock_resource:
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table
        mock_table.wait_until_exists = MagicMock()

        storage = DynamoDbStorage(
            table_name="test_table",
            region_name="us-west-2",
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",
            create_table_if_not_exists=False,
        )

        mock_resource.assert_called_once_with(
            "dynamodb",
            region_name="us-west-2",
            aws_access_key_id="test-key",
            aws_secret_access_key="test-secret",
            endpoint_url=None,
        )

    # Test with endpoint_url (for local testing)
    with patch("agno.storage.dynamodb.boto3.resource") as mock_resource:
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table
        mock_table.wait_until_exists = MagicMock()

        storage = DynamoDbStorage(
            table_name="test_table", endpoint_url="http://localhost:8000", create_table_if_not_exists=False
        )

        mock_resource.assert_called_once_with(
            "dynamodb",
            region_name=None,
            aws_access_key_id=None,
            aws_secret_access_key=None,
            endpoint_url="http://localhost:8000",
        )


def test_agent_storage_crud(agent_storage):
    """Test CRUD operations for agent storage."""
    storage, mock_table = agent_storage

    # Create a test session
    session = AgentSession(
        session_id="test-session",
        agent_id="test-agent",
        user_id="test-user",
        memory={"key": "value"},
        agent_data={"name": "Test Agent"},
        session_data={"state": "active"},
        extra_data={"custom": "data"},
    )

    # Test upsert
    mock_table.put_item.return_value = {}  # DynamoDB put_item returns empty dict on success
    mock_table.get_item.return_value = {"Item": session.to_dict()}  # Mock the read after upsert

    result = storage.upsert(session)
    assert result is not None
    assert result.session_id == session.session_id
    assert result.agent_id == session.agent_id
    mock_table.put_item.assert_called_once()

    # Test read
    mock_table.get_item.reset_mock()
    session_dict = session.to_dict()
    mock_table.get_item.return_value = {"Item": session_dict}
    read_result = storage.read("test-session")
    assert read_result is not None
    assert read_result.session_id == session.session_id
    assert read_result.agent_id == session.agent_id
    assert read_result.user_id == session.user_id
    mock_table.get_item.assert_called_once_with(Key={"session_id": "test-session"})

    # Test read with non-existent session
    mock_table.get_item.reset_mock()
    mock_table.get_item.return_value = {}  # DynamoDB returns empty dict when item not found
    read_result = storage.read("non-existent-session")
    assert read_result is None
    mock_table.get_item.assert_called_once_with(Key={"session_id": "non-existent-session"})

    # Test delete
    mock_table.delete_item.return_value = {}  # DynamoDB delete_item returns empty dict on success
    storage.delete_session("test-session")
    mock_table.delete_item.assert_called_once_with(Key={"session_id": "test-session"})


def test_workflow_storage_crud(workflow_storage):
    """Test CRUD operations for workflow storage."""
    storage, mock_table = workflow_storage

    # Create a test session
    session = WorkflowSession(
        session_id="test-session",
        workflow_id="test-workflow",
        user_id="test-user",
        memory={"key": "value"},
        workflow_data={"name": "Test Workflow"},
        session_data={"state": "active"},
        extra_data={"custom": "data"},
    )

    # Mock the read method
    original_read = storage.read
    storage.read = MagicMock(return_value=session)

    # Test upsert
    result = storage.upsert(session)
    assert result == session
    mock_table.put_item.assert_called_once()

    # Test read
    mock_table.get_item.return_value = {"Item": session.to_dict()}
    storage.read = original_read
    read_result = storage.read("test-session")
    assert read_result is not None
    assert read_result.session_id == session.session_id

    # Test delete
    storage.delete_session = MagicMock()
    storage.delete_session("test-session")
    storage.delete_session.assert_called_once_with("test-session")


def test_get_all_sessions(agent_storage):
    """Test retrieving all sessions."""
    storage, mock_table = agent_storage

    # Create mock sessions
    sessions = []
    for i in range(4):
        session_data = {
            "session_id": f"session-{i}",
            "agent_id": f"agent-{i % 2 + 1}",
            "user_id": f"user-{i % 2 + 1}",
            "memory": {},
            "agent_data": {},
            "session_data": {},
            "extra_data": {},
            "created_at": 1000000,
            "updated_at": None,
        }
        sessions.append(session_data)

    # Mock scan response for unfiltered query
    mock_table.scan.return_value = {"Items": sessions}

    # Test get_all_sessions without filters
    result = storage.get_all_sessions()
    assert len(result) == 4
    assert all(isinstance(s, AgentSession) for s in result)
    mock_table.scan.assert_called_once_with(
        ProjectionExpression="session_id, agent_id, user_id, team_session_id, memory, agent_data, session_data, extra_data, created_at, updated_at"
    )

    # Test filtering by user_id
    mock_table.scan.reset_mock()
    mock_table.query.reset_mock()
    user1_sessions = [s for s in sessions if s["user_id"] == "user-1"]
    mock_table.query.return_value = {"Items": user1_sessions}

    result = storage.get_all_sessions(user_id="user-1")
    assert len(result) == 2
    assert all(s.user_id == "user-1" for s in result)
    mock_table.query.assert_called_once_with(
        IndexName="user_id-index",
        KeyConditionExpression=Key("user_id").eq("user-1"),
        ProjectionExpression="session_id, agent_id, user_id, team_session_id, memory, agent_data, session_data, extra_data, created_at, updated_at",
    )

    # Test filtering by agent_id
    mock_table.query.reset_mock()
    agent1_sessions = [s for s in sessions if s["agent_id"] == "agent-1"]
    mock_table.query.return_value = {"Items": agent1_sessions}

    result = storage.get_all_sessions(entity_id="agent-1")
    assert len(result) == 2
    assert all(s.agent_id == "agent-1" for s in result)
    mock_table.query.assert_called_once_with(
        IndexName="agent_id-index",
        KeyConditionExpression=Key("agent_id").eq("agent-1"),
        ProjectionExpression="session_id, agent_id, user_id, team_session_id, memory, agent_data, session_data, extra_data, created_at, updated_at",
    )


def test_get_all_session_ids(agent_storage):
    """Test retrieving all session IDs."""
    storage, mock_table = agent_storage

    # Mock the scan method to return session IDs
    mock_response = {"Items": [{"session_id": "session-1"}, {"session_id": "session-2"}, {"session_id": "session-3"}]}
    mock_table.scan.return_value = mock_response

    # Test get_all_session_ids without filters
    result = storage.get_all_session_ids()
    assert result == ["session-1", "session-2", "session-3"]
    mock_table.scan.assert_called_once_with(ProjectionExpression="session_id")

    # Test with user_id filter
    mock_table.scan.reset_mock()
    mock_table.query.return_value = mock_response

    result = storage.get_all_session_ids(user_id="test-user")
    assert result == ["session-1", "session-2", "session-3"]
    mock_table.query.assert_called_once_with(
        IndexName="user_id-index",
        KeyConditionExpression=Key("user_id").eq("test-user"),
        ProjectionExpression="session_id",
    )

    # Test with entity_id filter (agent_id in agent mode)
    mock_table.query.reset_mock()
    mock_table.query.return_value = mock_response

    result = storage.get_all_session_ids(entity_id="test-agent")
    assert result == ["session-1", "session-2", "session-3"]
    mock_table.query.assert_called_once_with(
        IndexName="agent_id-index",
        KeyConditionExpression=Key("agent_id").eq("test-agent"),
        ProjectionExpression="session_id",
    )


def test_drop_table(agent_storage):
    """Test dropping a table."""
    storage, mock_table = agent_storage

    # Mock the delete and wait_until_not_exists methods
    mock_table.delete = MagicMock()
    mock_table.wait_until_not_exists = MagicMock()

    # Call drop
    storage.drop()

    # Verify delete was called
    mock_table.delete.assert_called_once()
    mock_table.wait_until_not_exists.assert_called_once()


def test_mode_switching():
    """Test switching between agent and workflow modes."""
    with patch("agno.storage.dynamodb.boto3.resource") as mock_resource:
        mock_table = MagicMock()
        mock_resource.return_value.Table.return_value = mock_table
        mock_table.wait_until_exists = MagicMock()

        # Create storage in agent mode
        storage = DynamoDbStorage(table_name="test_table", create_table_if_not_exists=False)
        assert storage.mode == "agent"

        # Switch to workflow mode
        with patch.object(storage, "create") as mock_create:
            storage.mode = "workflow"
            assert storage.mode == "workflow"
            # Since create_table_if_not_exists is False, create should not be called
            mock_create.assert_not_called()

        # Test with create_table_if_not_exists=True
        storage.create_table_if_not_exists = True
        with patch.object(storage, "create") as mock_create:
            storage.mode = "agent"
            assert storage.mode == "agent"
            mock_create.assert_called_once()


def test_serialization_deserialization(agent_storage):
    """Test serialization and deserialization of items."""
    storage, _ = agent_storage

    # Test serialization
    test_item = {
        "int_value": 42,
        "float_value": 3.14,
        "str_value": "test",
        "bool_value": True,
        "list_value": [1, 2, 3],
        "dict_value": {"key": "value"},
        "nested_dict": {"nested": {"float": 1.23, "list": [4, 5, 6]}},
        "none_value": None,
    }

    serialized = storage._serialize_item(test_item)

    # None values should be removed
    assert "none_value" not in serialized

    # Test deserialization
    from decimal import Decimal

    decimal_item = {
        "int_value": Decimal("42"),
        "float_value": Decimal("3.14"),
        "str_value": "test",
        "bool_value": True,
        "list_value": [Decimal("1"), Decimal("2"), Decimal("3")],
        "dict_value": {"key": "value"},
        "nested_dict": {"nested": {"float": Decimal("1.23"), "list": [Decimal("4"), Decimal("5"), Decimal("6")]}},
    }

    deserialized = storage._deserialize_item(decimal_item)

    # Decimals should be converted to int or float
    assert isinstance(deserialized["int_value"], int)
    assert deserialized["int_value"] == 42

    assert isinstance(deserialized["float_value"], float)
    assert deserialized["float_value"] == 3.14

    # Nested values should also be converted
    assert isinstance(deserialized["list_value"][0], int)
    assert isinstance(deserialized["nested_dict"]["nested"]["float"], float)
    assert isinstance(deserialized["nested_dict"]["nested"]["list"][0], int)
