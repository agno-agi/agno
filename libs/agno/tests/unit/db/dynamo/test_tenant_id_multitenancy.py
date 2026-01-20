"""Tests for DynamoDB tenant_id multi-tenancy support.

These tests verify that:
1. tenant_id defaults to "default" when not specified
2. The _make_pk() helper correctly creates composite partition keys
3. Items are stored with composite pk format
4. The schemas have the correct GSIs for tenant_id queries
"""

import pytest

from agno.db.dynamo.dynamo import DynamoDb
from agno.db.dynamo.schemas import (
    CULTURAL_KNOWLEDGE_TABLE_SCHEMA,
    EVAL_TABLE_SCHEMA,
    KNOWLEDGE_TABLE_SCHEMA,
    METRICS_TABLE_SCHEMA,
    SESSION_TABLE_SCHEMA,
    SPAN_TABLE_SCHEMA,
    TRACE_TABLE_SCHEMA,
    USER_MEMORY_TABLE_SCHEMA,
)


class MockDynamoClient:
    """Mock DynamoDB client for testing without AWS credentials."""

    pass


class TestTenantIdDefault:
    """Test tenant_id default behavior for DynamoDb instantiation."""

    def test_tenant_id_defaults_to_default(self):
        """Test that tenant_id defaults to 'default' when not specified."""
        db = DynamoDb(db_client=MockDynamoClient())
        assert db.tenant_id == "default"

    def test_tenant_id_accepted_when_valid(self):
        """Test that a valid tenant_id is accepted."""
        db = DynamoDb(tenant_id="test-tenant-id", db_client=MockDynamoClient())
        assert db.tenant_id == "test-tenant-id"

    def test_tenant_id_can_be_custom_value(self):
        """Test that custom tenant_id values work correctly."""
        db = DynamoDb(tenant_id="my-company-prod", db_client=MockDynamoClient())
        assert db.tenant_id == "my-company-prod"


class TestMakePkHelper:
    """Test the _make_pk() helper method."""

    def test_make_pk_with_default_tenant_id(self):
        """Test that _make_pk uses default tenant_id when not specified."""
        db = DynamoDb(db_client=MockDynamoClient())
        pk = db._make_pk("entity-123")
        assert pk == "default#entity-123"

    def test_make_pk_creates_composite_key(self):
        """Test that _make_pk creates the correct composite key format."""
        db = DynamoDb(tenant_id="my-tenant", db_client=MockDynamoClient())
        pk = db._make_pk("entity-123")
        assert pk == "my-tenant#entity-123"

    def test_make_pk_with_special_characters(self):
        """Test that _make_pk handles special characters in entity_id."""
        db = DynamoDb(tenant_id="my-tenant", db_client=MockDynamoClient())
        pk = db._make_pk("entity:with:colons")
        assert pk == "my-tenant#entity:with:colons"

    def test_make_pk_with_uuid(self):
        """Test that _make_pk handles UUID entity_ids."""
        db = DynamoDb(tenant_id="prod-tenant", db_client=MockDynamoClient())
        pk = db._make_pk("550e8400-e29b-41d4-a716-446655440000")
        assert pk == "prod-tenant#550e8400-e29b-41d4-a716-446655440000"


class TestSchemaHasTenantIdAttributes:
    """Test that all table schemas have the required tenant_id attributes and GSIs."""

    @pytest.fixture
    def all_schemas(self):
        """Return all table schemas."""
        return [
            ("SESSION", SESSION_TABLE_SCHEMA),
            ("USER_MEMORY", USER_MEMORY_TABLE_SCHEMA),
            ("EVAL", EVAL_TABLE_SCHEMA),
            ("KNOWLEDGE", KNOWLEDGE_TABLE_SCHEMA),
            ("METRICS", METRICS_TABLE_SCHEMA),
            ("CULTURAL_KNOWLEDGE", CULTURAL_KNOWLEDGE_TABLE_SCHEMA),
            ("TRACE", TRACE_TABLE_SCHEMA),
            ("SPAN", SPAN_TABLE_SCHEMA),
        ]

    def test_all_schemas_use_pk_as_partition_key(self, all_schemas):
        """Test that all schemas use 'pk' as the partition key."""
        for name, schema in all_schemas:
            key_schema = schema["KeySchema"]
            hash_key = next((k for k in key_schema if k["KeyType"] == "HASH"), None)
            assert hash_key is not None, f"{name} schema missing HASH key"
            assert hash_key["AttributeName"] == "pk", f"{name} schema should use 'pk' as partition key"

    def test_all_schemas_have_tenant_id_attribute(self, all_schemas):
        """Test that all schemas have 'tenant_id' in AttributeDefinitions."""
        for name, schema in all_schemas:
            attr_defs = schema["AttributeDefinitions"]
            tenant_id_attr = next((a for a in attr_defs if a["AttributeName"] == "tenant_id"), None)
            assert tenant_id_attr is not None, f"{name} schema missing 'tenant_id' attribute"
            assert tenant_id_attr["AttributeType"] == "S", f"{name} schema 'tenant_id' should be string type"

    def test_all_schemas_have_tenant_id_gsi(self, all_schemas):
        """Test that all schemas have a tenant_id GSI for multi-tenancy queries."""
        for name, schema in all_schemas:
            gsis = schema.get("GlobalSecondaryIndexes", [])
            tenant_id_gsi = next((g for g in gsis if g["IndexName"].startswith("tenant_id-")), None)
            assert tenant_id_gsi is not None, f"{name} schema missing tenant_id GSI"

            # Verify the GSI has tenant_id as the partition key
            gsi_key_schema = tenant_id_gsi["KeySchema"]
            hash_key = next((k for k in gsi_key_schema if k["KeyType"] == "HASH"), None)
            assert hash_key is not None, f"{name} GSI missing HASH key"
            assert hash_key["AttributeName"] == "tenant_id", f"{name} GSI should use 'tenant_id' as partition key"


class TestSessionTenantIdSerialization:
    """Test that session data models include tenant_id."""

    def test_agent_session_has_tenant_id_field(self):
        """Test that AgentSession has tenant_id field."""
        from agno.session.agent import AgentSession

        session = AgentSession(session_id="test-session", tenant_id="test-tenant")
        assert session.tenant_id == "test-tenant"

        # Test serialization
        data = session.to_dict()
        assert data.get("tenant_id") == "test-tenant"

        # Test deserialization
        restored = AgentSession.from_dict(data)
        assert restored.tenant_id == "test-tenant"

    def test_team_session_has_tenant_id_field(self):
        """Test that TeamSession has tenant_id field."""
        from agno.session.team import TeamSession

        session = TeamSession(session_id="test-session", tenant_id="test-tenant")
        assert session.tenant_id == "test-tenant"

        # Test serialization
        data = session.to_dict()
        assert data.get("tenant_id") == "test-tenant"

        # Test deserialization
        restored = TeamSession.from_dict(data)
        assert restored.tenant_id == "test-tenant"

    def test_workflow_session_has_tenant_id_field(self):
        """Test that WorkflowSession has tenant_id field."""
        from agno.session.workflow import WorkflowSession

        session = WorkflowSession(session_id="test-session", tenant_id="test-tenant")
        assert session.tenant_id == "test-tenant"

        # Test serialization
        data = session.to_dict()
        assert data.get("tenant_id") == "test-tenant"

        # Test deserialization
        restored = WorkflowSession.from_dict(data)
        assert restored.tenant_id == "test-tenant"


class TestMemoryTenantIdSerialization:
    """Test that memory data models include tenant_id."""

    def test_user_memory_has_tenant_id_field(self):
        """Test that UserMemory has tenant_id field."""
        from agno.db.schemas.memory import UserMemory

        memory = UserMemory(
            memory_id="test-memory",
            memory="Test memory content",
            tenant_id="test-tenant",
        )
        assert memory.tenant_id == "test-tenant"

        # Test serialization
        data = memory.to_dict()
        assert data.get("tenant_id") == "test-tenant"


class TestCulturalKnowledgeTenantIdSerialization:
    """Test that cultural knowledge data models include tenant_id."""

    def test_cultural_knowledge_has_tenant_id_field(self):
        """Test that CulturalKnowledge has tenant_id field."""
        from agno.db.schemas.culture import CulturalKnowledge

        knowledge = CulturalKnowledge(
            id="test-knowledge",
            content="Test content",
            tenant_id="test-tenant",
        )
        assert knowledge.tenant_id == "test-tenant"

        # Test serialization
        data = knowledge.to_dict()
        assert data.get("tenant_id") == "test-tenant"


class TestEvalTenantIdSerialization:
    """Test that eval data models include tenant_id."""

    def test_eval_run_record_has_tenant_id_field(self):
        """Test that EvalRunRecord has tenant_id field."""
        from agno.db.schemas.evals import EvalRunRecord, EvalType

        record = EvalRunRecord(
            run_id="test-run",
            tenant_id="test-tenant",
            eval_type=EvalType.ACCURACY,
            eval_data={"score": 0.95},
        )
        assert record.tenant_id == "test-tenant"


class TestKnowledgeTenantIdSerialization:
    """Test that knowledge data models include tenant_id."""

    def test_knowledge_row_has_tenant_id_field(self):
        """Test that KnowledgeRow has tenant_id field."""
        from agno.db.schemas.knowledge import KnowledgeRow

        row = KnowledgeRow(
            id="test-row",
            tenant_id="test-tenant",
            name="Test Knowledge",
            description="Test description",
        )
        assert row.tenant_id == "test-tenant"
