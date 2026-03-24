from typing import Any, Dict, Optional


def _is_oauth_metadata(data: Any) -> bool:
    return isinstance(data, dict) and data.get("requirement_type") == "oauth" and bool(data.get("auth_url"))


def extract_oauth_from_exception(exc: Exception) -> Optional[Dict[str, Any]]:
    """Extract OAuth metadata from a StopAgentRun exception's additional_data."""
    extra = getattr(exc, "additional_data", None)
    return extra if _is_oauth_metadata(extra) else None


def extract_oauth_from_response(response: Any) -> Optional[Dict[str, Any]]:
    """Extract OAuth metadata from response.tools ToolExecution additional_data.

    StopAgentRun is caught at the model layer and surfaces as
    ToolExecution.additional_data on response.tools — not as an exception.
    """
    for tool in getattr(response, "tools", None) or []:
        extra = getattr(tool, "additional_data", None)
        if _is_oauth_metadata(extra):
            return extra
    return None
