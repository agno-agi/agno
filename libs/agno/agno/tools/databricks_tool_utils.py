from os import getenv
from typing import Any, Dict, List, Optional

from agno.databricks.settings import DatabricksSettings


def build_workspace_client_kwargs(settings: DatabricksSettings, azure_tenant_id: Optional[str] = None) -> Dict[str, Any]:
    client_kwargs: Dict[str, Any] = {}
    if settings.host:
        client_kwargs["host"] = settings.host
    if settings.token:
        client_kwargs["token"] = settings.token
    if settings.client_id:
        client_kwargs["client_id"] = settings.client_id
    if settings.client_secret:
        client_kwargs["client_secret"] = settings.client_secret
    if azure_tenant_id:
        client_kwargs["azure_tenant_id"] = azure_tenant_id
    return client_kwargs


def build_vector_search_client_kwargs(
    settings: DatabricksSettings,
    disable_notice: bool,
    azure_tenant_id: Optional[str] = None,
    azure_login_id: Optional[str] = None,
) -> Dict[str, Any]:
    client_kwargs: Dict[str, Any] = {
        "workspace_url": settings.workspace_url,
        "personal_access_token": settings.token,
        "service_principal_client_id": settings.client_id,
        "service_principal_client_secret": settings.client_secret,
        "disable_notice": disable_notice,
    }
    if azure_tenant_id is not None:
        client_kwargs["azure_tenant_id"] = azure_tenant_id
    if azure_login_id is not None:
        client_kwargs["azure_login_id"] = azure_login_id
    return {key: value for key, value in client_kwargs.items() if value is not None}


def resolve_admin_settings(
    toolkit_name: str,
    host: Optional[str] = None,
    admin_token: Optional[str] = None,
    admin_client_id: Optional[str] = None,
    admin_client_secret: Optional[str] = None,
    enable_admin_tools: bool = False,
    injected_client: Optional[Any] = None,
) -> Optional[DatabricksSettings]:
    if not enable_admin_tools:
        return None

    resolved_admin_token = admin_token or getenv("DATABRICKS_ADMIN_TOKEN")
    resolved_admin_client_id = admin_client_id or getenv("DATABRICKS_ADMIN_CLIENT_ID")
    resolved_admin_client_secret = admin_client_secret or getenv("DATABRICKS_ADMIN_CLIENT_SECRET")

    if injected_client is None:
        has_pat_admin_auth = resolved_admin_token is not None and resolved_admin_token.strip() != ""
        has_oauth_admin_auth = bool(resolved_admin_client_id) and bool(resolved_admin_client_secret)
        has_partial_oauth_admin_auth = bool(resolved_admin_client_id) != bool(resolved_admin_client_secret)

        if has_partial_oauth_admin_auth:
            raise ValueError(
                f"{toolkit_name} requires both admin_client_id and admin_client_secret when using OAuth admin credentials."
            )

        if not has_pat_admin_auth and not has_oauth_admin_auth:
            raise ValueError(
                f"{toolkit_name} requires explicit admin credentials via admin_token or admin_client_id/admin_client_secret when enable_admin_tools=True."
            )

    return DatabricksSettings.from_values(
        host=host,
        token=resolved_admin_token,
        client_id=resolved_admin_client_id,
        client_secret=resolved_admin_client_secret,
    )


def admin_tools_disabled_error(toolkit_name: str, operation_name: str) -> str:
    return (
        f"Error {operation_name}: {toolkit_name} requires enable_admin_tools=True and explicit admin credentials "
        "to expose Databricks admin operations."
    )


def serialize_sdk_item(item: Any) -> Dict[str, Any]:
    """Serialize a Databricks SDK object to a dictionary."""
    if item is None:
        return {}
    if isinstance(item, dict):
        return item
    if hasattr(item, "as_dict") and callable(item.as_dict):
        return item.as_dict()
    if hasattr(item, "as_shallow_dict") and callable(item.as_shallow_dict):
        return item.as_shallow_dict()
    if hasattr(item, "__dict__"):
        return {k: v for k, v in item.__dict__.items() if not k.startswith("_")}
    return {"value": str(item)}


def serialize_sdk_items(items: Any, limit: Optional[int], max_results: int) -> List[Dict[str, Any]]:
    """Serialize an iterable of Databricks SDK objects to a list of dictionaries."""
    if items is None:
        return []
    if isinstance(items, dict):
        for wrapper_key in ("endpoints", "indexes", "items", "elements", "results", "data"):
            inner = items.get(wrapper_key)
            if isinstance(inner, list):
                items = inner
                break
        else:
            return [items]
    effective_limit = max_results if limit is None else min(limit, max_results)
    serialized: List[Dict[str, Any]] = []
    for index, item in enumerate(items):
        if index >= effective_limit:
            break
        serialized.append(serialize_sdk_item(item))
    return serialized
