import json

import pytest

from agno.tools.databricks_vector_search import DatabricksVectorSearchTools


class _SdkObject:
    def __init__(self, payload):
        self._payload = payload

    def as_dict(self):
        return self._payload


def test_list_endpoints_and_indexes():
    client = type("VectorSearchClient", (), {})()
    client.list_endpoints = lambda: [_SdkObject({"name": "vs-endpoint"})]
    client.list_indexes = lambda name: [_SdkObject({"name": f"{name}.index"})]

    tools = DatabricksVectorSearchTools(
        vector_search_client=client,
        default_endpoint_name="vs-endpoint",
    )

    endpoints = tools.list_endpoints(limit=10)
    indexes = tools.list_indexes(limit=10)

    assert json.loads(endpoints) == [{"name": "vs-endpoint"}]
    assert json.loads(indexes) == [{"name": "vs-endpoint.index"}]


def test_create_endpoint_forwards_arguments_and_requires_confirmation():
    captured = {}

    client = type("VectorSearchClient", (), {})()

    def _create_endpoint(**kwargs):
        captured["kwargs"] = kwargs
        return {"name": kwargs["name"], "endpoint_type": kwargs["endpoint_type"]}

    client.create_endpoint = _create_endpoint

    tools = DatabricksVectorSearchTools(vector_search_client=client, enable_admin_tools=True)

    result = tools.create_endpoint(
        endpoint_name="agno-vector-endpoint",
        endpoint_type="STANDARD",
        budget_policy_id="budget-1",
        usage_policy_id="usage-1",
    )

    assert captured["kwargs"] == {
        "name": "agno-vector-endpoint",
        "endpoint_type": "STANDARD",
        "budget_policy_id": "budget-1",
        "usage_policy_id": "usage-1",
    }
    assert json.loads(result) == {"name": "agno-vector-endpoint", "endpoint_type": "STANDARD"}
    assert "create_endpoint" in tools.requires_confirmation_tools


def test_create_delta_sync_index_with_computed_embeddings():
    captured = {}

    client = type("VectorSearchClient", (), {})()

    def _create_delta_sync_index(**kwargs):
        captured["kwargs"] = kwargs
        return {"name": kwargs["index_name"], "pipeline_type": kwargs["pipeline_type"]}

    client.create_delta_sync_index = _create_delta_sync_index

    tools = DatabricksVectorSearchTools(
        vector_search_client=client,
        default_endpoint_name="vs-endpoint",
        enable_admin_tools=True,
    )

    result = tools.create_delta_sync_index(
        index_name="workspace.default.docs_idx",
        source_table_name="workspace.default.docs",
        primary_key="id",
        embedding_source_column="content",
        embedding_model_endpoint_name="gte-endpoint",
        model_endpoint_name_for_query="gte-query-endpoint",
        columns_to_sync=["title", "author"],
    )

    assert captured["kwargs"] == {
        "endpoint_name": "vs-endpoint",
        "source_table_name": "workspace.default.docs",
        "index_name": "workspace.default.docs_idx",
        "pipeline_type": "TRIGGERED",
        "primary_key": "id",
        "embedding_source_column": "content",
        "embedding_model_endpoint_name": "gte-endpoint",
        "model_endpoint_name_for_query": "gte-query-endpoint",
        "columns_to_sync": ["title", "author"],
    }
    assert json.loads(result) == {"name": "workspace.default.docs_idx", "pipeline_type": "TRIGGERED"}


def test_create_delta_sync_index_with_existing_embeddings():
    captured = {}

    client = type("VectorSearchClient", (), {})()

    def _create_delta_sync_index(**kwargs):
        captured["kwargs"] = kwargs
        return {"name": kwargs["index_name"], "embedding_dimension": kwargs["embedding_dimension"]}

    client.create_delta_sync_index = _create_delta_sync_index

    tools = DatabricksVectorSearchTools(
        vector_search_client=client,
        default_endpoint_name="vs-endpoint",
        enable_admin_tools=True,
    )

    result = tools.create_delta_sync_index(
        index_name="workspace.default.docs_idx",
        source_table_name="workspace.default.docs",
        primary_key="id",
        embedding_vector_column="content_vector",
        embedding_dimension=1024,
    )

    assert captured["kwargs"] == {
        "endpoint_name": "vs-endpoint",
        "source_table_name": "workspace.default.docs",
        "index_name": "workspace.default.docs_idx",
        "pipeline_type": "TRIGGERED",
        "primary_key": "id",
        "embedding_vector_column": "content_vector",
        "embedding_dimension": 1024,
    }
    assert json.loads(result) == {"name": "workspace.default.docs_idx", "embedding_dimension": 1024}
    assert "create_delta_sync_index" in tools.requires_confirmation_tools


def test_create_delta_sync_index_validates_embedding_mode():
    tools = DatabricksVectorSearchTools(
        vector_search_client=object(),
        default_endpoint_name="vs-endpoint",
        enable_admin_tools=True,
    )

    missing_mode = tools.create_delta_sync_index(
        index_name="workspace.default.docs_idx",
        source_table_name="workspace.default.docs",
        primary_key="id",
    )
    mixed_mode = tools.create_delta_sync_index(
        index_name="workspace.default.docs_idx",
        source_table_name="workspace.default.docs",
        primary_key="id",
        embedding_source_column="content",
        embedding_model_endpoint_name="gte-endpoint",
        embedding_vector_column="content_vector",
        embedding_dimension=1024,
    )

    assert "provide either" in missing_mode
    assert "provide either" in mixed_mode


def test_create_direct_access_index_forwards_arguments():
    captured = {}

    client = type("VectorSearchClient", (), {})()

    def _create_direct_access_index(**kwargs):
        captured["kwargs"] = kwargs
        return {"name": kwargs["index_name"], "primary_key": kwargs["primary_key"]}

    client.create_direct_access_index = _create_direct_access_index

    tools = DatabricksVectorSearchTools(
        vector_search_client=client,
        default_endpoint_name="vs-endpoint",
        enable_admin_tools=True,
    )

    result = tools.create_direct_access_index(
        index_name="workspace.default.direct_idx",
        primary_key="id",
        embedding_dimension=1024,
        embedding_vector_column="content_vector",
        schema={"id": "string", "content_vector": "array<float>"},
    )

    assert captured["kwargs"] == {
        "endpoint_name": "vs-endpoint",
        "index_name": "workspace.default.direct_idx",
        "primary_key": "id",
        "embedding_dimension": 1024,
        "embedding_vector_column": "content_vector",
        "schema": {"id": "string", "content_vector": "array<float>"},
    }
    assert json.loads(result) == {"name": "workspace.default.direct_idx", "primary_key": "id"}
    assert "create_direct_access_index" in tools.requires_confirmation_tools


def test_serialization_redacts_sensitive_fields():
    sdk_object = type(
        "SdkObject",
        (),
        {
            "__dict__": {
                "name": "workspace.default.docs_idx",
                "personal_access_token": "secret-token",
                "service_principal_client_secret": "secret-client",
            }
        },
    )()

    tools = DatabricksVectorSearchTools(vector_search_client=object())

    serialized = tools._serialize_item(sdk_object)

    assert serialized["name"] == "workspace.default.docs_idx"
    assert serialized["personal_access_token"] == "***REDACTED***"
    assert serialized["service_principal_client_secret"] == "***REDACTED***"


def test_describe_index():
    index = type("VectorSearchIndex", (), {})()
    index.describe = lambda: {"name": "main.analytics.docs", "status": "ONLINE"}

    client = type("VectorSearchClient", (), {})()
    client.get_index = lambda endpoint_name, index_name: index

    tools = DatabricksVectorSearchTools(
        vector_search_client=client,
        default_endpoint_name="vs-endpoint",
        default_index_name="main.analytics.docs",
    )

    result = tools.describe_index()

    assert json.loads(result) == {"name": "main.analytics.docs", "status": "ONLINE"}


def test_query_index_forwards_arguments():
    captured = {}
    index = type("VectorSearchIndex", (), {})()

    def _similarity_search(**kwargs):
        captured["kwargs"] = kwargs
        return {"result": {"data_array": [["doc_1", "hello"]]}}

    index.similarity_search = _similarity_search

    client = type("VectorSearchClient", (), {})()
    client.get_index = lambda endpoint_name, index_name: index

    tools = DatabricksVectorSearchTools(
        vector_search_client=client,
        default_endpoint_name="vs-endpoint",
        default_index_name="main.analytics.docs",
    )

    result = tools.query_index(
        columns=["id", "content"],
        query_text="hello world",
        filters={"topic": "ai"},
        num_results=3,
        query_type="HYBRID",
        score_threshold=0.2,
        debug_level=1,
    )

    assert captured["kwargs"] == {
        "columns": ["id", "content"],
        "query_text": "hello world",
        "query_vector": None,
        "filters": {"topic": "ai"},
        "num_results": 3,
        "query_type": "HYBRID",
        "score_threshold": 0.2,
        "debug_level": 1,
        "disable_notice": True,
    }
    assert json.loads(result) == {"result": {"data_array": [["doc_1", "hello"]]}}


def test_query_index_requires_query_or_vector():
    tools = DatabricksVectorSearchTools(vector_search_client=object())

    result = tools.query_index(columns=["id"])

    assert "query_text or query_vector is required" in result


def test_sync_upsert_delete_and_confirmation_flags():
    index = type("VectorSearchIndex", (), {})()
    index.sync = lambda: {"status": "QUEUED"}
    index.upsert = lambda inputs: {"status": "SUCCESS", "count": len(inputs)}
    index.delete = lambda primary_keys: {"status": "SUCCESS", "count": len(primary_keys)}

    client = type("VectorSearchClient", (), {})()
    client.get_index = lambda endpoint_name, index_name: index

    tools = DatabricksVectorSearchTools(
        vector_search_client=client,
        default_endpoint_name="vs-endpoint",
        default_index_name="main.analytics.docs",
        enable_admin_tools=True,
    )

    assert json.loads(tools.sync_index()) == {"status": "QUEUED"}
    assert json.loads(tools.upsert_vectors(inputs=[{"id": "doc_1"}])) == {"status": "SUCCESS", "count": 1}
    assert json.loads(tools.delete_vectors(primary_keys=["doc_1"])) == {"status": "SUCCESS", "count": 1}
    assert "sync_index" in tools.requires_confirmation_tools
    assert "upsert_vectors" in tools.requires_confirmation_tools
    assert "delete_vectors" in tools.requires_confirmation_tools


def test_upsert_and_delete_validate_non_empty_payloads():
    tools = DatabricksVectorSearchTools(vector_search_client=object(), enable_admin_tools=True)

    upsert_result = tools.upsert_vectors(inputs=[])
    delete_result = tools.delete_vectors(primary_keys=[])

    assert "inputs cannot be empty" in upsert_result
    assert "primary_keys cannot be empty" in delete_result


def test_vector_search_tools_hide_admin_operations_by_default():
    tools = DatabricksVectorSearchTools(vector_search_client=object())

    assert "create_endpoint" not in tools.functions
    assert "create_delta_sync_index" not in tools.functions
    assert "create_direct_access_index" not in tools.functions
    assert "sync_index" not in tools.functions
    assert "upsert_vectors" not in tools.functions
    assert "delete_vectors" not in tools.functions
    assert tools.requires_confirmation_tools == []


def test_vector_search_tools_reject_admin_operations_without_enable_flag():
    client = type("VectorSearchClient", (), {})()
    tools = DatabricksVectorSearchTools(
        vector_search_client=client,
        default_endpoint_name="vs-endpoint",
        default_index_name="main.analytics.docs",
    )

    create_result = tools.create_endpoint("agno-vector-endpoint")
    sync_result = tools.sync_index()
    upsert_result = tools.upsert_vectors(inputs=[{"id": "doc_1"}])
    delete_result = tools.delete_vectors(primary_keys=["doc_1"])

    assert "enable_admin_tools=True" in create_result
    assert "enable_admin_tools=True" in sync_result
    assert "enable_admin_tools=True" in upsert_result
    assert "enable_admin_tools=True" in delete_result


def test_vector_search_tools_require_explicit_admin_credentials_without_injected_client():
    with pytest.raises(ValueError, match="explicit admin credentials"):
        DatabricksVectorSearchTools(enable_admin_tools=True)
