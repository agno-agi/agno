import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.databricks.settings import DatabricksSettings
from agno.tools import Toolkit
from agno.tools.databricks_tool_utils import (
    admin_tools_disabled_error,
    build_vector_search_client_kwargs,
    resolve_admin_settings,
)
from agno.utils.log import log_error

SENSITIVE_FIELD_NAMES = {
    "personal_access_token",
    "token",
    "service_principal_client_secret",
    "api_key",
    "authorization",
}


def _get_vector_search_client_cls():
    try:
        from databricks.vector_search.client import VectorSearchClient  # type: ignore[import-not-found,import-untyped]
    except ImportError as exc:
        raise ImportError(
            "`databricks-vectorsearch` not installed. Please install using `pip install databricks-vectorsearch`."
        ) from exc
    return VectorSearchClient


class DatabricksVectorSearchTools(Toolkit):
    """Native Databricks Vector Search tools with approval-gated mutation methods."""

    def __init__(
        self,
        host: Optional[str] = None,
        token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        admin_token: Optional[str] = None,
        admin_client_id: Optional[str] = None,
        admin_client_secret: Optional[str] = None,
        enable_admin_tools: bool = False,
        azure_tenant_id: Optional[str] = None,
        azure_login_id: Optional[str] = None,
        vector_search_client: Optional[Any] = None,
        default_endpoint_name: Optional[str] = None,
        default_index_name: Optional[str] = None,
        max_results: int = 100,
        disable_notice: bool = True,
        enable_create_endpoint: bool = True,
        enable_create_delta_sync_index: bool = True,
        enable_create_direct_access_index: bool = True,
        enable_list_endpoints: bool = True,
        enable_list_indexes: bool = True,
        enable_describe_index: bool = True,
        enable_query_index: bool = True,
        enable_sync_index: bool = True,
        enable_upsert_vectors: bool = True,
        enable_delete_vectors: bool = True,
        all: bool = False,  # noqa: A002
        **kwargs,
    ):
        self.settings = DatabricksSettings.from_values(
            host=host,
            token=token,
            client_id=client_id,
            client_secret=client_secret,
        )
        self.admin_settings = resolve_admin_settings(
            toolkit_name="DatabricksVectorSearchTools",
            host=host,
            admin_token=admin_token,
            admin_client_id=admin_client_id,
            admin_client_secret=admin_client_secret,
            enable_admin_tools=enable_admin_tools,
            injected_client=vector_search_client,
        )
        self.enable_admin_tools = enable_admin_tools
        self.azure_tenant_id = azure_tenant_id or getenv("DATABRICKS_AZURE_TENANT_ID")
        self.azure_login_id = azure_login_id or getenv("DATABRICKS_AZURE_LOGIN_ID")
        self.default_endpoint_name = default_endpoint_name or getenv("DATABRICKS_VECTOR_SEARCH_ENDPOINT")
        self.default_index_name = default_index_name or getenv("DATABRICKS_VECTOR_SEARCH_INDEX")
        self.max_results = max_results
        self.disable_notice = disable_notice
        self._client = vector_search_client
        self._admin_client: Optional[Any] = vector_search_client if enable_admin_tools else None

        tools: List[Any] = []
        if self.enable_admin_tools and (enable_create_endpoint or all):
            tools.append(self.create_endpoint)
        if self.enable_admin_tools and (enable_create_delta_sync_index or all):
            tools.append(self.create_delta_sync_index)
        if self.enable_admin_tools and (enable_create_direct_access_index or all):
            tools.append(self.create_direct_access_index)
        if enable_list_endpoints or all:
            tools.append(self.list_endpoints)
        if enable_list_indexes or all:
            tools.append(self.list_indexes)
        if enable_describe_index or all:
            tools.append(self.describe_index)
        if enable_query_index or all:
            tools.append(self.query_index)
        if self.enable_admin_tools and (enable_sync_index or all):
            tools.append(self.sync_index)
        if self.enable_admin_tools and (enable_upsert_vectors or all):
            tools.append(self.upsert_vectors)
        if self.enable_admin_tools and (enable_delete_vectors or all):
            tools.append(self.delete_vectors)

        requires_confirmation_tools: List[str] = []
        if self.enable_admin_tools:
            if enable_create_endpoint or all:
                requires_confirmation_tools.append("create_endpoint")
            if enable_create_delta_sync_index or all:
                requires_confirmation_tools.append("create_delta_sync_index")
            if enable_create_direct_access_index or all:
                requires_confirmation_tools.append("create_direct_access_index")
            if enable_sync_index or all:
                requires_confirmation_tools.append("sync_index")
            if enable_upsert_vectors or all:
                requires_confirmation_tools.append("upsert_vectors")
            if enable_delete_vectors or all:
                requires_confirmation_tools.append("delete_vectors")

        instructions = kwargs.pop(
            "instructions",
            "Use these tools for Databricks Vector Search inspection and retrieval. Create, sync, upsert, and delete operations are only available when explicitly enabled with dedicated admin credentials and still require approval.",
        )
        add_instructions = kwargs.pop("add_instructions", True)

        super().__init__(
            name="databricks_vector_search_tools",
            tools=tools,
            instructions=instructions,
            add_instructions=add_instructions,
            requires_confirmation_tools=requires_confirmation_tools,
            **kwargs,
        )

    @property
    def client(self) -> Any:
        if self._client is None:
            client_cls = _get_vector_search_client_cls()
            self._client = client_cls(
                **build_vector_search_client_kwargs(
                    self.settings,
                    disable_notice=self.disable_notice,
                    azure_tenant_id=self.azure_tenant_id,
                    azure_login_id=self.azure_login_id,
                )
            )
        return self._client

    @property
    def admin_client(self) -> Any:
        if not self.enable_admin_tools:
            raise RuntimeError(
                admin_tools_disabled_error("DatabricksVectorSearchTools", "modifying Databricks vector search resources")
            )

        if self._admin_client is None:
            client_cls = _get_vector_search_client_cls()
            if self.admin_settings is None:
                raise RuntimeError(
                    admin_tools_disabled_error(
                        "DatabricksVectorSearchTools", "modifying Databricks vector search resources"
                    )
                )
            self._admin_client = client_cls(
                **build_vector_search_client_kwargs(
                    self.admin_settings,
                    disable_notice=self.disable_notice,
                    azure_tenant_id=self.azure_tenant_id,
                    azure_login_id=self.azure_login_id,
                )
            )
        return self._admin_client

    def list_endpoints(self, limit: Optional[int] = None) -> str:
        """Use this function to list Databricks Vector Search endpoints."""
        try:
            endpoints = self.client.list_endpoints()
            return json.dumps(self._serialize_items(endpoints, limit), default=str)
        except Exception as e:
            log_error(f"Error listing Databricks vector search endpoints: {str(e)}")
            return "Error listing Databricks vector search endpoints: An internal error occurred. Check server logs for details."

    def create_endpoint(
        self,
        endpoint_name: str,
        endpoint_type: str = "STANDARD",
        budget_policy_id: Optional[str] = None,
        usage_policy_id: Optional[str] = None,
    ) -> str:
        """Use this function to create a Databricks Vector Search endpoint."""
        if not self.enable_admin_tools:
            return admin_tools_disabled_error(
                "DatabricksVectorSearchTools", "creating Databricks vector search endpoints"
            )
        if not endpoint_name.strip():
            return "Error creating Databricks vector search endpoint: endpoint_name is required"
        try:
            response = self.admin_client.create_endpoint(
                name=endpoint_name,
                endpoint_type=endpoint_type,
                budget_policy_id=budget_policy_id,
                usage_policy_id=usage_policy_id,
            )
            return json.dumps(self._serialize_item(response), default=str)
        except Exception as e:
            log_error(f"Error creating Databricks vector search endpoint: {str(e)}")
            return "Error creating Databricks vector search endpoint: An internal error occurred. Check server logs for details."

    def create_delta_sync_index(
        self,
        index_name: str,
        source_table_name: str,
        primary_key: str,
        endpoint_name: Optional[str] = None,
        pipeline_type: str = "TRIGGERED",
        embedding_source_column: Optional[str] = None,
        embedding_model_endpoint_name: Optional[str] = None,
        model_endpoint_name_for_query: Optional[str] = None,
        embedding_vector_column: Optional[str] = None,
        embedding_dimension: Optional[int] = None,
        columns_to_sync: Optional[List[str]] = None,
    ) -> str:
        """Use this function to create a Databricks Delta Sync Vector Search index."""
        if not self.enable_admin_tools:
            return admin_tools_disabled_error("DatabricksVectorSearchTools", "creating Databricks vector search indexes")
        resolved_endpoint = endpoint_name or self.default_endpoint_name
        if not resolved_endpoint:
            return "Error creating Databricks delta sync vector search index: endpoint_name is required"
        if not index_name.strip():
            return "Error creating Databricks delta sync vector search index: index_name is required"
        if not source_table_name.strip():
            return "Error creating Databricks delta sync vector search index: source_table_name is required"
        if not primary_key.strip():
            return "Error creating Databricks delta sync vector search index: primary_key is required"

        uses_computed_embeddings = embedding_source_column is not None or embedding_model_endpoint_name is not None
        uses_existing_embeddings = embedding_vector_column is not None or embedding_dimension is not None
        if uses_computed_embeddings == uses_existing_embeddings:
            return (
                "Error creating Databricks delta sync vector search index: provide either "
                "(embedding_source_column and embedding_model_endpoint_name) or "
                "(embedding_vector_column and embedding_dimension)"
            )
        if uses_computed_embeddings and (embedding_source_column is None or embedding_model_endpoint_name is None):
            return (
                "Error creating Databricks delta sync vector search index: "
                "embedding_source_column and embedding_model_endpoint_name are both required"
            )
        if uses_existing_embeddings and (embedding_vector_column is None or embedding_dimension is None):
            return (
                "Error creating Databricks delta sync vector search index: "
                "embedding_vector_column and embedding_dimension are both required"
            )

        try:
            request: Dict[str, Any] = {
                "endpoint_name": resolved_endpoint,
                "source_table_name": source_table_name,
                "index_name": index_name,
                "pipeline_type": pipeline_type,
                "primary_key": primary_key,
            }
            if embedding_source_column is not None:
                request["embedding_source_column"] = embedding_source_column
                request["embedding_model_endpoint_name"] = embedding_model_endpoint_name
                if model_endpoint_name_for_query is not None:
                    request["model_endpoint_name_for_query"] = model_endpoint_name_for_query
            else:
                request["embedding_vector_column"] = embedding_vector_column
                request["embedding_dimension"] = embedding_dimension
            if columns_to_sync:
                request["columns_to_sync"] = columns_to_sync

            response = self.admin_client.create_delta_sync_index(**request)
            return json.dumps(self._serialize_item(response), default=str)
        except Exception as e:
            log_error(f"Error creating Databricks delta sync vector search index: {str(e)}")
            return "Error creating Databricks delta sync vector search index: An internal error occurred. Check server logs for details."

    def create_direct_access_index(
        self,
        index_name: str,
        primary_key: str,
        embedding_dimension: int,
        embedding_vector_column: str,
        schema: Dict[str, str],
        endpoint_name: Optional[str] = None,
    ) -> str:
        """Use this function to create a Databricks Direct Access Vector Search index."""
        if not self.enable_admin_tools:
            return admin_tools_disabled_error("DatabricksVectorSearchTools", "creating Databricks vector search indexes")
        resolved_endpoint = endpoint_name or self.default_endpoint_name
        if not resolved_endpoint:
            return "Error creating Databricks direct access vector search index: endpoint_name is required"
        if not index_name.strip():
            return "Error creating Databricks direct access vector search index: index_name is required"
        if not primary_key.strip():
            return "Error creating Databricks direct access vector search index: primary_key is required"
        if embedding_dimension <= 0:
            return "Error creating Databricks direct access vector search index: embedding_dimension must be greater than 0"
        if not embedding_vector_column.strip():
            return "Error creating Databricks direct access vector search index: embedding_vector_column is required"
        if not schema:
            return "Error creating Databricks direct access vector search index: schema is required"

        try:
            response = self.admin_client.create_direct_access_index(
                endpoint_name=resolved_endpoint,
                index_name=index_name,
                primary_key=primary_key,
                embedding_dimension=embedding_dimension,
                embedding_vector_column=embedding_vector_column,
                schema=schema,
            )
            return json.dumps(self._serialize_item(response), default=str)
        except Exception as e:
            log_error(f"Error creating Databricks direct access vector search index: {str(e)}")
            return "Error creating Databricks direct access vector search index: An internal error occurred. Check server logs for details."

    def list_indexes(self, endpoint_name: Optional[str] = None, limit: Optional[int] = None) -> str:
        """Use this function to list indexes under a Databricks Vector Search endpoint."""
        resolved_endpoint = endpoint_name or self.default_endpoint_name
        if not resolved_endpoint:
            return "Error listing Databricks vector search indexes: endpoint_name is required"
        try:
            indexes = self.client.list_indexes(name=resolved_endpoint)
            return json.dumps(self._serialize_items(indexes, limit), default=str)
        except Exception as e:
            log_error(f"Error listing Databricks vector search indexes: {str(e)}")
            return "Error listing Databricks vector search indexes: An internal error occurred. Check server logs for details."

    def describe_index(self, index_name: Optional[str] = None, endpoint_name: Optional[str] = None) -> str:
        """Use this function to describe a Databricks Vector Search index."""
        try:
            index = self._get_index(endpoint_name=endpoint_name, index_name=index_name)
            return json.dumps(self._serialize_item(index.describe()), default=str)
        except Exception as e:
            log_error(f"Error describing Databricks vector search index: {str(e)}")
            return "Error describing Databricks vector search index: An internal error occurred. Check server logs for details."

    def query_index(
        self,
        columns: List[str],
        query_text: Optional[str] = None,
        query_vector: Optional[List[float]] = None,
        endpoint_name: Optional[str] = None,
        index_name: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        num_results: int = 5,
        query_type: Optional[str] = None,
        score_threshold: Optional[float] = None,
        debug_level: int = 0,
    ) -> str:
        """Use this function to query a Databricks Vector Search index."""
        if not query_text and not query_vector:
            return "Error querying Databricks vector search index: query_text or query_vector is required"
        if not columns:
            return "Error querying Databricks vector search index: at least one column is required"
        try:
            index = self._get_index(endpoint_name=endpoint_name, index_name=index_name)
            response = index.similarity_search(
                columns=columns,
                query_text=query_text,
                query_vector=query_vector,
                filters=filters,
                num_results=num_results,
                query_type=query_type,
                score_threshold=score_threshold,
                debug_level=debug_level,
                disable_notice=self.disable_notice,
            )
            return json.dumps(response, default=str)
        except Exception as e:
            log_error(f"Error querying Databricks vector search index: {str(e)}")
            return "Error querying Databricks vector search index: An internal error occurred. Check server logs for details."

    def sync_index(self, index_name: Optional[str] = None, endpoint_name: Optional[str] = None) -> str:
        """Use this function to trigger a sync for a triggered Databricks delta-sync index."""
        if not self.enable_admin_tools:
            return admin_tools_disabled_error("DatabricksVectorSearchTools", "syncing Databricks vector search indexes")
        try:
            index = self._get_index(endpoint_name=endpoint_name, index_name=index_name, use_admin_client=True)
            response = index.sync()
            return json.dumps(self._serialize_item(response), default=str)
        except Exception as e:
            log_error(f"Error syncing Databricks vector search index: {str(e)}")
            return "Error syncing Databricks vector search index: An internal error occurred. Check server logs for details."

    def upsert_vectors(
        self,
        inputs: List[Dict[str, Any]],
        index_name: Optional[str] = None,
        endpoint_name: Optional[str] = None,
    ) -> str:
        """Use this function to upsert rows into a Databricks direct-access vector search index."""
        if not self.enable_admin_tools:
            return admin_tools_disabled_error(
                "DatabricksVectorSearchTools", "upserting Databricks vector search vectors"
            )
        if not inputs:
            return "Error upserting Databricks vector search vectors: inputs cannot be empty"
        try:
            index = self._get_index(endpoint_name=endpoint_name, index_name=index_name, use_admin_client=True)
            response = index.upsert(inputs)
            return json.dumps(self._serialize_item(response), default=str)
        except Exception as e:
            log_error(f"Error upserting Databricks vector search vectors: {str(e)}")
            return "Error upserting Databricks vector search vectors: An internal error occurred. Check server logs for details."

    def delete_vectors(
        self,
        primary_keys: List[Any],
        index_name: Optional[str] = None,
        endpoint_name: Optional[str] = None,
    ) -> str:
        """Use this function to delete rows from a Databricks vector search index by primary key."""
        if not self.enable_admin_tools:
            return admin_tools_disabled_error(
                "DatabricksVectorSearchTools", "deleting Databricks vector search vectors"
            )
        if not primary_keys:
            return "Error deleting Databricks vector search vectors: primary_keys cannot be empty"
        try:
            index = self._get_index(endpoint_name=endpoint_name, index_name=index_name, use_admin_client=True)
            response = index.delete(primary_keys=primary_keys)
            return json.dumps(self._serialize_item(response), default=str)
        except Exception as e:
            log_error(f"Error deleting Databricks vector search vectors: {str(e)}")
            return "Error deleting Databricks vector search vectors: An internal error occurred. Check server logs for details."

    def _get_index(self, endpoint_name: Optional[str], index_name: Optional[str], use_admin_client: bool = False):
        resolved_endpoint = endpoint_name or self.default_endpoint_name
        resolved_index = index_name or self.default_index_name
        if not resolved_index:
            raise ValueError("index_name is required")
        client = self.admin_client if use_admin_client else self.client
        return client.get_index(endpoint_name=resolved_endpoint, index_name=resolved_index)

    def _serialize_items(self, items, limit=None) -> List[Dict[str, Any]]:
        from agno.tools.databricks_tool_utils import serialize_sdk_items
        return serialize_sdk_items(items, limit, self.max_results)

    def _serialize_item(self, item: Any) -> Dict[str, Any]:
        from agno.tools.databricks_tool_utils import serialize_sdk_item
        result = serialize_sdk_item(item)
        return self._sanitize_item(result)

    def _sanitize_item(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: ("***REDACTED***" if key.lower() in SENSITIVE_FIELD_NAMES else self._sanitize_item(item))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._sanitize_item(item) for item in value]
        if isinstance(value, tuple):
            return [self._sanitize_item(item) for item in value]
        return value
