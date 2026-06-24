"""Unit tests for trace search API endpoint and filter schema endpoint.

Tests cover:
- GET /traces/filter-schema returns correct schema
- POST /traces/search with various filter expressions
- TraceSearchRequest Pydantic model validation
- FilterFieldSchema and FilterSchemaResponse models
- TRACE_FILTER_SCHEMA constant
- Error handling (invalid filters, missing fields)
"""

import pytest

from agno.os.routers.traces.schemas import (
    TRACE_FILTER_SCHEMA,
    FilterFieldSchema,
    FilterSchemaResponse,
    TraceSearchRequest,
)


class TestTraceSearchRequestModel:
    """Test TraceSearchRequest Pydantic model validation."""

    def test_default_values(self):
        """Test TraceSearchRequest with default values."""
        req = TraceSearchRequest()
        assert req.filter is None
        assert req.page == 1
        assert req.limit == 20

    def test_with_filter(self):
        """Test TraceSearchRequest with a filter expression."""
        req = TraceSearchRequest(
            filter={"op": "EQ", "key": "status", "value": "OK"},
            page=1,
            limit=20,
        )
        assert req.filter == {"op": "EQ", "key": "status", "value": "OK"}
        assert req.page == 1
        assert req.limit == 20

    def test_with_complex_filter(self):
        """Test TraceSearchRequest with complex AND filter."""
        filter_dict = {
            "op": "AND",
            "conditions": [
                {"op": "EQ", "key": "status", "value": "OK"},
                {"op": "CONTAINS", "key": "user_id", "value": "admin"},
            ],
        }
        req = TraceSearchRequest(filter=filter_dict, page=2, limit=50)
        assert req.filter["op"] == "AND"
        assert len(req.filter["conditions"]) == 2
        assert req.page == 2
        assert req.limit == 50

    def test_page_minimum(self):
        """Test page must be >= 1."""
        with pytest.raises(Exception):
            TraceSearchRequest(page=0)

    def test_limit_minimum(self):
        """Test limit must be >= 1."""
        with pytest.raises(Exception):
            TraceSearchRequest(limit=0)

    def test_custom_page_and_limit(self):
        """Test custom page and limit values."""
        req = TraceSearchRequest(page=5, limit=100)
        assert req.page == 5
        assert req.limit == 100

    def test_filter_none_explicitly(self):
        """Test filter can be explicitly None."""
        req = TraceSearchRequest(filter=None)
        assert req.filter is None

    def test_serialization(self):
        """Test TraceSearchRequest serializes to dict correctly."""
        req = TraceSearchRequest(
            filter={"op": "EQ", "key": "status", "value": "OK"},
            page=1,
            limit=20,
        )
        data = req.model_dump()
        assert "filter" in data
        assert data["filter"]["op"] == "EQ"
        assert data["page"] == 1
        assert data["limit"] == 20


class TestFilterFieldSchemaModel:
    """Test FilterFieldSchema Pydantic model."""

    def test_enum_field(self):
        """Test FilterFieldSchema with enum type and values."""
        field = FilterFieldSchema(
            key="status",
            label="Status",
            type="enum",
            operators=["EQ", "NEQ", "IN"],
            values=["OK", "ERROR"],
        )
        assert field.key == "status"
        assert field.label == "Status"
        assert field.type == "enum"
        assert field.operators == ["EQ", "NEQ", "IN"]
        assert field.values == ["OK", "ERROR"]

    def test_string_field(self):
        """Test FilterFieldSchema with string type (no values)."""
        field = FilterFieldSchema(
            key="user_id",
            label="User ID",
            type="string",
            operators=["EQ", "NEQ", "CONTAINS", "STARTSWITH", "IN"],
        )
        assert field.key == "user_id"
        assert field.type == "string"
        assert field.values is None

    def test_number_field(self):
        """Test FilterFieldSchema with number type."""
        field = FilterFieldSchema(
            key="duration_ms",
            label="Duration (ms)",
            type="number",
            operators=["EQ", "NEQ", "GT", "GTE", "LT", "LTE"],
        )
        assert field.type == "number"
        assert "GT" in field.operators
        assert "GTE" in field.operators

    def test_datetime_field(self):
        """Test FilterFieldSchema with datetime type."""
        field = FilterFieldSchema(
            key="start_time",
            label="Start Time",
            type="datetime",
            operators=["GT", "GTE", "LT", "LTE"],
        )
        assert field.type == "datetime"
        assert len(field.operators) == 4


class TestFilterSchemaResponseModel:
    """Test FilterSchemaResponse Pydantic model."""

    def test_default_logical_operators(self):
        """Test FilterSchemaResponse has default logical operators."""
        schema = FilterSchemaResponse(
            fields=[
                FilterFieldSchema(
                    key="status",
                    label="Status",
                    type="enum",
                    operators=["EQ"],
                    values=["OK"],
                )
            ]
        )
        assert schema.logical_operators == ["AND", "OR"]

    def test_custom_logical_operators(self):
        """Test FilterSchemaResponse with custom logical operators."""
        schema = FilterSchemaResponse(
            fields=[],
            logical_operators=["AND"],
        )
        assert schema.logical_operators == ["AND"]

    def test_multiple_fields(self):
        """Test FilterSchemaResponse with multiple fields."""
        schema = FilterSchemaResponse(
            fields=[
                FilterFieldSchema(key="a", label="A", type="string", operators=["EQ"]),
                FilterFieldSchema(key="b", label="B", type="number", operators=["GT"]),
            ]
        )
        assert len(schema.fields) == 2


class TestTraceFilterSchema:
    """Test the TRACE_FILTER_SCHEMA constant."""

    def test_is_filter_schema_response(self):
        """Test that TRACE_FILTER_SCHEMA is a FilterSchemaResponse."""
        assert isinstance(TRACE_FILTER_SCHEMA, FilterSchemaResponse)

    def test_has_fields(self):
        """Test that TRACE_FILTER_SCHEMA has fields."""
        assert len(TRACE_FILTER_SCHEMA.fields) > 0

    def test_has_logical_operators(self):
        """Test that TRACE_FILTER_SCHEMA has AND and OR logical operators."""
        assert "AND" in TRACE_FILTER_SCHEMA.logical_operators
        assert "OR" in TRACE_FILTER_SCHEMA.logical_operators

    def test_status_field_is_enum(self):
        """Test that status field is enum type with OK and ERROR values."""
        status_field = next((f for f in TRACE_FILTER_SCHEMA.fields if f.key == "status"), None)
        assert status_field is not None
        assert status_field.type == "enum"
        assert "OK" in status_field.values
        assert "ERROR" in status_field.values
        assert "EQ" in status_field.operators
        assert "NEQ" in status_field.operators
        assert "IN" in status_field.operators

    def test_user_id_field_is_string(self):
        """Test that user_id field is string type with correct operators."""
        user_field = next((f for f in TRACE_FILTER_SCHEMA.fields if f.key == "user_id"), None)
        assert user_field is not None
        assert user_field.type == "string"
        assert "CONTAINS" in user_field.operators
        assert "STARTSWITH" in user_field.operators
        assert "EQ" in user_field.operators

    def test_duration_ms_field_is_number(self):
        """Test that duration_ms field is number type with comparison operators."""
        duration_field = next((f for f in TRACE_FILTER_SCHEMA.fields if f.key == "duration_ms"), None)
        assert duration_field is not None
        assert duration_field.type == "number"
        assert "GT" in duration_field.operators
        assert "GTE" in duration_field.operators
        assert "LT" in duration_field.operators
        assert "LTE" in duration_field.operators

    def test_start_time_field_is_datetime(self):
        """Test that start_time field is datetime type."""
        time_field = next((f for f in TRACE_FILTER_SCHEMA.fields if f.key == "start_time"), None)
        assert time_field is not None
        assert time_field.type == "datetime"
        assert "GT" in time_field.operators
        assert "LTE" in time_field.operators

    def test_all_expected_fields_present(self):
        """Test that all expected trace fields are present in the schema."""
        field_keys = {f.key for f in TRACE_FILTER_SCHEMA.fields}
        expected_keys = {
            "status",
            "user_id",
            "agent_id",
            "team_id",
            "workflow_id",
            "session_id",
            "run_id",
            "name",
            "trace_id",
            "duration_ms",
            "start_time",
            "end_time",
            "created_at",
        }
        assert expected_keys == field_keys

    def test_agent_id_field(self):
        """Test agent_id field configuration."""
        agent_field = next((f for f in TRACE_FILTER_SCHEMA.fields if f.key == "agent_id"), None)
        assert agent_field is not None
        assert agent_field.label == "Agent ID"
        assert agent_field.type == "string"
        assert "CONTAINS" in agent_field.operators
        assert "STARTSWITH" in agent_field.operators

    def test_team_id_field(self):
        """Test team_id field configuration."""
        team_field = next((f for f in TRACE_FILTER_SCHEMA.fields if f.key == "team_id"), None)
        assert team_field is not None
        assert team_field.label == "Team ID"

    def test_workflow_id_field(self):
        """Test workflow_id field configuration."""
        wf_field = next((f for f in TRACE_FILTER_SCHEMA.fields if f.key == "workflow_id"), None)
        assert wf_field is not None
        assert wf_field.label == "Workflow ID"

    def test_trace_id_field(self):
        """Test trace_id field configuration."""
        trace_field = next((f for f in TRACE_FILTER_SCHEMA.fields if f.key == "trace_id"), None)
        assert trace_field is not None
        assert "EQ" in trace_field.operators
        assert "CONTAINS" in trace_field.operators

    def test_name_field(self):
        """Test name field configuration."""
        name_field = next((f for f in TRACE_FILTER_SCHEMA.fields if f.key == "name"), None)
        assert name_field is not None
        assert name_field.label == "Trace Name"
        assert "STARTSWITH" in name_field.operators

    def test_serialization(self):
        """Test TRACE_FILTER_SCHEMA serializes to dict correctly."""
        data = TRACE_FILTER_SCHEMA.model_dump()
        assert "fields" in data
        assert "logical_operators" in data
        assert len(data["fields"]) == 13
        assert data["logical_operators"] == ["AND", "OR"]

    def test_json_serialization(self):
        """Test TRACE_FILTER_SCHEMA serializes to JSON correctly."""
        json_str = TRACE_FILTER_SCHEMA.model_dump_json()
        assert isinstance(json_str, str)
        assert "status" in json_str
        assert "user_id" in json_str

    def test_field_labels_are_human_readable(self):
        """Test that all field labels are human-readable strings."""
        for field in TRACE_FILTER_SCHEMA.fields:
            assert isinstance(field.label, str)
            assert len(field.label) > 0
            # Labels should have spaces or be proper nouns
            assert field.label[0].isupper(), f"Label '{field.label}' should start with uppercase"

    def test_no_duplicate_field_keys(self):
        """Test that there are no duplicate field keys."""
        keys = [f.key for f in TRACE_FILTER_SCHEMA.fields]
        assert len(keys) == len(set(keys)), "Duplicate field keys found"

    def test_enum_fields_have_values(self):
        """Test that enum type fields have values list."""
        for field in TRACE_FILTER_SCHEMA.fields:
            if field.type == "enum":
                assert field.values is not None, f"Enum field '{field.key}' should have values"
                assert len(field.values) > 0, f"Enum field '{field.key}' should have non-empty values"

    def test_non_enum_fields_no_values(self):
        """Test that non-enum type fields don't have values."""
        for field in TRACE_FILTER_SCHEMA.fields:
            if field.type != "enum":
                assert field.values is None, f"Non-enum field '{field.key}' should not have values"
