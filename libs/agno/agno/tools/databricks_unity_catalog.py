import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.databricks.settings import DatabricksSettings
from agno.tools import Toolkit
from agno.utils.log import log_error


def _get_workspace_client_cls():
    try:
        from databricks.sdk import WorkspaceClient  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError("`databricks-sdk` not installed. Please install using `pip install databricks-sdk`.") from exc
    return WorkspaceClient


class DatabricksUnityCatalogTools(Toolkit):
    """Read-only Unity Catalog tools implemented with the native Databricks SDK."""

    def __init__(
        self,
        host: Optional[str] = None,
        token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        azure_tenant_id: Optional[str] = None,
        workspace_client: Optional[Any] = None,
        default_catalog: Optional[str] = None,
        default_schema: Optional[str] = None,
        max_results: int = 100,
        enable_list_catalogs: bool = True,
        enable_list_schemas: bool = True,
        enable_list_tables: bool = True,
        enable_get_table_metadata: bool = True,
        enable_list_functions: bool = True,
        enable_get_function_metadata: bool = True,
        enable_list_volumes: bool = True,
        all: bool = False,  # noqa: A002
        **kwargs,
    ):
        self.settings = DatabricksSettings.from_values(
            host=host,
            token=token,
            client_id=client_id,
            client_secret=client_secret,
        )
        self.azure_tenant_id = azure_tenant_id or getenv("DATABRICKS_AZURE_TENANT_ID")
        self.default_catalog = default_catalog or getenv("DATABRICKS_CATALOG")
        self.default_schema = default_schema or getenv("DATABRICKS_SCHEMA")
        self.max_results = max_results
        self._workspace_client = workspace_client

        tools: List[Any] = []
        if enable_list_catalogs or all:
            tools.append(self.list_catalogs)
        if enable_list_schemas or all:
            tools.append(self.list_schemas)
        if enable_list_tables or all:
            tools.append(self.list_tables)
        if enable_get_table_metadata or all:
            tools.append(self.get_table_metadata)
        if enable_list_functions or all:
            tools.append(self.list_functions)
        if enable_get_function_metadata or all:
            tools.append(self.get_function_metadata)
        if enable_list_volumes or all:
            tools.append(self.list_volumes)

        instructions = kwargs.pop(
            "instructions",
            "Use these tools for Databricks Unity Catalog metadata discovery only. Do not use them for create, update, or delete operations.",
        )
        add_instructions = kwargs.pop("add_instructions", True)

        super().__init__(
            name="databricks_unity_catalog_tools",
            tools=tools,
            instructions=instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

    @property
    def client(self) -> Any:
        if self._workspace_client is None:
            from agno.tools.databricks_tool_utils import build_workspace_client_kwargs
            client_cls = _get_workspace_client_cls()
            client_kwargs = build_workspace_client_kwargs(self.settings, azure_tenant_id=self.azure_tenant_id)
            self._workspace_client = client_cls(**client_kwargs)
        return self._workspace_client

    def list_catalogs(self, include_browse: bool = False, limit: Optional[int] = None) -> str:
        """Use this function to list Unity Catalog catalogs."""
        try:
            catalogs = self.client.catalogs.list(include_browse=include_browse, max_results=limit or self.max_results)
            return json.dumps(self._serialize_items(catalogs, limit), default=str)
        except Exception as e:
            log_error(f"Error listing Databricks catalogs: {str(e)}")
            return "Error listing Databricks catalogs: An internal error occurred. Check server logs for details."

    def list_schemas(self, catalog_name: Optional[str] = None, include_browse: bool = False, limit: Optional[int] = None) -> str:
        """Use this function to list schemas under a Unity Catalog catalog."""
        resolved_catalog = catalog_name or self.default_catalog
        if not resolved_catalog:
            return "Error listing Databricks schemas: catalog_name is required"
        try:
            schemas = self.client.schemas.list(
                catalog_name=resolved_catalog,
                include_browse=include_browse,
                max_results=limit or self.max_results,
            )
            return json.dumps(self._serialize_items(schemas, limit), default=str)
        except Exception as e:
            log_error(f"Error listing Databricks schemas: {str(e)}")
            return "Error listing Databricks schemas: An internal error occurred. Check server logs for details."

    def list_tables(
        self,
        catalog_name: Optional[str] = None,
        schema_name: Optional[str] = None,
        include_browse: bool = False,
        limit: Optional[int] = None,
    ) -> str:
        """Use this function to list Unity Catalog tables and views."""
        resolved_catalog = catalog_name or self.default_catalog
        resolved_schema = schema_name or self.default_schema
        if not resolved_catalog or not resolved_schema:
            return "Error listing Databricks tables: catalog_name and schema_name are required"
        try:
            tables = self.client.tables.list(
                catalog_name=resolved_catalog,
                schema_name=resolved_schema,
                include_browse=include_browse,
                max_results=limit or self.max_results,
                omit_columns=True,
                omit_properties=True,
            )
            return json.dumps(self._serialize_items(tables, limit), default=str)
        except Exception as e:
            log_error(f"Error listing Databricks tables: {str(e)}")
            return "Error listing Databricks tables: An internal error occurred. Check server logs for details."

    def get_table_metadata(
        self,
        full_name: str,
        include_browse: bool = False,
        include_delta_metadata: bool = False,
        include_manifest_capabilities: bool = False,
    ) -> str:
        """Use this function to fetch metadata for a Unity Catalog table or view."""
        try:
            table = self.client.tables.get(
                full_name=full_name,
                include_browse=include_browse,
                include_delta_metadata=include_delta_metadata,
                include_manifest_capabilities=include_manifest_capabilities,
            )
            return json.dumps(self._serialize_item(table), default=str)
        except Exception as e:
            log_error(f"Error getting Databricks table metadata: {str(e)}")
            return "Error getting Databricks table metadata: An internal error occurred. Check server logs for details."

    def list_functions(
        self,
        catalog_name: Optional[str] = None,
        schema_name: Optional[str] = None,
        include_browse: bool = False,
        limit: Optional[int] = None,
    ) -> str:
        """Use this function to list Unity Catalog functions."""
        resolved_catalog = catalog_name or self.default_catalog
        resolved_schema = schema_name or self.default_schema
        if not resolved_catalog or not resolved_schema:
            return "Error listing Databricks functions: catalog_name and schema_name are required"
        try:
            functions = self.client.functions.list(
                catalog_name=resolved_catalog,
                schema_name=resolved_schema,
                include_browse=include_browse,
                max_results=limit or self.max_results,
            )
            return json.dumps(self._serialize_items(functions, limit), default=str)
        except Exception as e:
            log_error(f"Error listing Databricks functions: {str(e)}")
            return "Error listing Databricks functions: An internal error occurred. Check server logs for details."

    def get_function_metadata(self, full_name: str, include_browse: bool = False) -> str:
        """Use this function to fetch metadata for a Unity Catalog function."""
        try:
            function = self.client.functions.get(name=full_name, include_browse=include_browse)
            return json.dumps(self._serialize_item(function), default=str)
        except Exception as e:
            log_error(f"Error getting Databricks function metadata: {str(e)}")
            return "Error getting Databricks function metadata: An internal error occurred. Check server logs for details."

    def list_volumes(
        self,
        catalog_name: Optional[str] = None,
        schema_name: Optional[str] = None,
        include_browse: bool = False,
        limit: Optional[int] = None,
    ) -> str:
        """Use this function to list Unity Catalog volumes."""
        resolved_catalog = catalog_name or self.default_catalog
        resolved_schema = schema_name or self.default_schema
        if not resolved_catalog or not resolved_schema:
            return "Error listing Databricks volumes: catalog_name and schema_name are required"
        try:
            volumes = self.client.volumes.list(
                catalog_name=resolved_catalog,
                schema_name=resolved_schema,
                include_browse=include_browse,
                max_results=limit or self.max_results,
            )
            return json.dumps(self._serialize_items(volumes, limit), default=str)
        except Exception as e:
            log_error(f"Error listing Databricks volumes: {str(e)}")
            return "Error listing Databricks volumes: An internal error occurred. Check server logs for details."

    def _serialize_items(self, items, limit=None) -> List[Dict[str, Any]]:
        from agno.tools.databricks_tool_utils import serialize_sdk_items
        return serialize_sdk_items(items, limit, self.max_results)

    def _serialize_item(self, item: Any) -> Dict[str, Any]:
        from agno.tools.databricks_tool_utils import serialize_sdk_item
        return serialize_sdk_item(item)
