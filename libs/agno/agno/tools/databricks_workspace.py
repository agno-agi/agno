import base64
import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.databricks.settings import DatabricksSettings
from agno.tools import Toolkit
from agno.tools.databricks_tool_utils import (
    admin_tools_disabled_error,
    build_workspace_client_kwargs,
    resolve_admin_settings,
)
from agno.utils.log import log_error


def _get_workspace_sdk():
    try:
        from databricks.sdk import WorkspaceClient  # type: ignore[import-not-found]
        from databricks.sdk.service import workspace as workspace_service  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError("`databricks-sdk` not installed. Please install using `pip install databricks-sdk`.") from exc
    return WorkspaceClient, workspace_service


class DatabricksWorkspaceTools(Toolkit):
    """Workspace and notebook management tools using the native Databricks SDK."""

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
        workspace_client: Optional[Any] = None,
        max_results: int = 100,
        enable_list_workspace_objects: bool = True,
        enable_get_workspace_object_status: bool = True,
        enable_create_directory: bool = True,
        enable_create_notebook: bool = True,
        enable_import_notebook: bool = True,
        enable_export_notebook: bool = True,
        enable_delete_workspace_object: bool = True,
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
            toolkit_name="DatabricksWorkspaceTools",
            host=host,
            admin_token=admin_token,
            admin_client_id=admin_client_id,
            admin_client_secret=admin_client_secret,
            enable_admin_tools=enable_admin_tools,
            injected_client=workspace_client,
        )
        self.enable_admin_tools = enable_admin_tools
        self.azure_tenant_id = azure_tenant_id or getenv("DATABRICKS_AZURE_TENANT_ID")
        self.max_results = max_results
        self._workspace_client = workspace_client
        self._admin_workspace_client: Optional[Any] = workspace_client if enable_admin_tools else None

        tools: List[Any] = []
        if enable_list_workspace_objects or all:
            tools.append(self.list_workspace_objects)
        if enable_get_workspace_object_status or all:
            tools.append(self.get_workspace_object_status)
        if self.enable_admin_tools and (enable_create_directory or all):
            tools.append(self.create_directory)
        if self.enable_admin_tools and (enable_create_notebook or all):
            tools.append(self.create_notebook)
        if self.enable_admin_tools and (enable_import_notebook or all):
            tools.append(self.import_notebook)
        if enable_export_notebook or all:
            tools.append(self.export_notebook)
        if self.enable_admin_tools and (enable_delete_workspace_object or all):
            tools.append(self.delete_workspace_object)

        requires_confirmation_tools: List[str] = []
        if self.enable_admin_tools:
            if enable_create_directory or all:
                requires_confirmation_tools.append("create_directory")
            if enable_create_notebook or all:
                requires_confirmation_tools.append("create_notebook")
            if enable_import_notebook or all:
                requires_confirmation_tools.append("import_notebook")
            if enable_delete_workspace_object or all:
                requires_confirmation_tools.append("delete_workspace_object")

        instructions = kwargs.pop(
            "instructions",
            "Use these tools for Databricks workspace inspection and notebook export. Creating, importing, or deleting workspace objects is only available when explicitly enabled with dedicated admin credentials and still requires approval.",
        )
        add_instructions = kwargs.pop("add_instructions", True)

        super().__init__(
            name="databricks_workspace_tools",
            tools=tools,
            instructions=instructions,
            add_instructions=add_instructions,
            requires_confirmation_tools=requires_confirmation_tools,
            **kwargs,
        )

    @property
    def client(self) -> Any:
        if self._workspace_client is None:
            workspace_client_cls, _ = _get_workspace_sdk()
            self._workspace_client = workspace_client_cls(
                **build_workspace_client_kwargs(self.settings, azure_tenant_id=self.azure_tenant_id)
            )
        return self._workspace_client

    @property
    def admin_client(self) -> Any:
        if not self.enable_admin_tools:
            raise RuntimeError(
                admin_tools_disabled_error("DatabricksWorkspaceTools", "modifying Databricks workspace objects")
            )

        if self._admin_workspace_client is None:
            workspace_client_cls, _ = _get_workspace_sdk()
            if self.admin_settings is None:
                raise RuntimeError(
                    admin_tools_disabled_error("DatabricksWorkspaceTools", "modifying Databricks workspace objects")
                )
            self._admin_workspace_client = workspace_client_cls(
                **build_workspace_client_kwargs(self.admin_settings, azure_tenant_id=self.azure_tenant_id)
            )
        return self._admin_workspace_client

    def list_workspace_objects(self, path: str, limit: Optional[int] = None, recursive: bool = False) -> str:
        """Use this function to list objects under a Databricks workspace path."""
        try:
            items = self.client.workspace.list(path=path, recursive=recursive)
            return json.dumps(self._serialize_items(items, limit), default=str)
        except Exception as e:
            log_error(f"Error listing Databricks workspace objects: {str(e)}")
            return "Error listing Databricks workspace objects: An internal error occurred. Check server logs for details."

    def get_workspace_object_status(self, path: str) -> str:
        """Use this function to get metadata for a Databricks workspace object."""
        try:
            status = self.client.workspace.get_status(path=path)
            return json.dumps(self._serialize_item(status), default=str)
        except Exception as e:
            log_error(f"Error getting Databricks workspace object status: {str(e)}")
            return "Error getting Databricks workspace object status: An internal error occurred. Check server logs for details."

    def create_directory(self, path: str) -> str:
        """Use this function to create a directory in the Databricks workspace."""
        if not self.enable_admin_tools:
            return admin_tools_disabled_error("DatabricksWorkspaceTools", "creating Databricks workspace directories")
        try:
            self.admin_client.workspace.mkdirs(path=path)
            return json.dumps({"path": path, "created": True})
        except Exception as e:
            log_error(f"Error creating Databricks workspace directory: {str(e)}")
            return "Error creating Databricks workspace directory: An internal error occurred. Check server logs for details."

    def create_notebook(
        self,
        path: str,
        language: str,
        content: str,
        overwrite: bool = False,
        file_format: str = "SOURCE",
    ) -> str:
        """Use this function to create a Databricks notebook from source text."""
        if not self.enable_admin_tools:
            return admin_tools_disabled_error("DatabricksWorkspaceTools", "creating Databricks notebooks")
        try:
            _, workspace_service = _get_workspace_sdk()
            language_upper = language.upper()
            if not hasattr(workspace_service.Language, language_upper) or language_upper.startswith("_"):
                return "Error creating Databricks notebook: unsupported language '{language}'"
            file_format_upper = file_format.upper()
            if not hasattr(workspace_service.ImportFormat, file_format_upper) or file_format_upper.startswith("_"):
                return "Error creating Databricks notebook: unsupported format '{file_format}'"
            self.admin_client.workspace.import_(
                path=path,
                content=base64.b64encode(content.encode("utf-8")).decode("utf-8"),
                format=getattr(workspace_service.ImportFormat, file_format_upper),
                language=getattr(workspace_service.Language, language_upper),
                overwrite=overwrite,
            )
            return json.dumps({"path": path, "created": True, "language": language.upper()})
        except Exception as e:
            log_error(f"Error creating Databricks notebook: {str(e)}")
            return "Error creating Databricks notebook: An internal error occurred. Check server logs for details."

    def import_notebook(
        self,
        path: str,
        content_base64: str,
        overwrite: bool = False,
        file_format: str = "SOURCE",
        language: Optional[str] = None,
    ) -> str:
        """Use this function to import a Databricks notebook or workspace file from base64 content."""
        if not self.enable_admin_tools:
            return admin_tools_disabled_error("DatabricksWorkspaceTools", "importing Databricks notebooks")
        try:
            import base64 as b64lib

            try:
                b64lib.b64decode(content_base64, validate=True)
            except Exception:
                return "Error importing Databricks notebook: content_base64 is not valid base64"

            _, workspace_service = _get_workspace_sdk()
            file_format_upper = file_format.upper()
            if not hasattr(workspace_service.ImportFormat, file_format_upper) or file_format_upper.startswith("_"):
                return "Error importing Databricks notebook: unsupported format '{file_format}'"
            import_kwargs: Dict[str, Any] = {
                "path": path,
                "content": content_base64,
                "format": getattr(workspace_service.ImportFormat, file_format_upper),
                "overwrite": overwrite,
            }
            if language is not None:
                import_kwargs["language"] = getattr(workspace_service.Language, language.upper())
            self.admin_client.workspace.import_(**import_kwargs)
            return json.dumps({"path": path, "imported": True})
        except Exception as e:
            log_error(f"Error importing Databricks notebook: {str(e)}")
            return "Error importing Databricks notebook: An internal error occurred. Check server logs for details."

    def export_notebook(self, path: str, file_format: str = "SOURCE") -> str:
        """Use this function to export a Databricks notebook or workspace file."""
        try:
            _, workspace_service = _get_workspace_sdk()
            file_format_upper = file_format.upper()
            if not hasattr(workspace_service.ExportFormat, file_format_upper) or file_format_upper.startswith("_"):
                return "Error exporting Databricks notebook: unsupported format '{file_format}'"
            response = self.client.workspace.export_(path=path, format=getattr(workspace_service.ExportFormat, file_format_upper))
            return json.dumps(self._serialize_item(response), default=str)
        except Exception as e:
            log_error(f"Error exporting Databricks notebook: {str(e)}")
            return "Error exporting Databricks notebook: An internal error occurred. Check server logs for details."

    def delete_workspace_object(self, path: str, recursive: bool = False) -> str:
        """Use this function to delete a Databricks workspace object or directory."""
        if not self.enable_admin_tools:
            return admin_tools_disabled_error("DatabricksWorkspaceTools", "deleting Databricks workspace objects")
        try:
            self.admin_client.workspace.delete(path=path, recursive=recursive)
            return json.dumps({"path": path, "deleted": True, "recursive": recursive})
        except Exception as e:
            log_error(f"Error deleting Databricks workspace object: {str(e)}")
            return "Error deleting Databricks workspace object: An internal error occurred. Check server logs for details."

    def _serialize_items(self, items, limit=None) -> List[Dict[str, Any]]:
        from agno.tools.databricks_tool_utils import serialize_sdk_items
        return serialize_sdk_items(items, limit, self.max_results)

    def _serialize_item(self, item: Any) -> Dict[str, Any]:
        from agno.tools.databricks_tool_utils import serialize_sdk_item
        return serialize_sdk_item(item)
