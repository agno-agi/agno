"""Shared utility helpers for Team."""

from __future__ import annotations

import json
from copy import copy
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Union,
    cast,
)

if TYPE_CHECKING:
    from agno.team.team import Team

from agno.filters import FilterExpr
from agno.utils.log import log_debug, log_error, log_warning


def _get_effective_filters(
    team: Team, knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
) -> Optional[Any]:
    """
    Determine effective filters for the team, considering:
    1. Team-level filters (team.knowledge_filters)
    2. Run-time filters (knowledge_filters)

    Priority: Run-time filters > Team filters
    """
    effective_filters = None

    # Start with team-level filters if they exist
    if team.knowledge_filters:
        effective_filters = team.knowledge_filters.copy()

    # Apply run-time filters if they exist
    if knowledge_filters:
        if effective_filters:
            if isinstance(effective_filters, dict):
                if isinstance(knowledge_filters, dict):
                    effective_filters.update(cast(Dict[str, Any], knowledge_filters))
                else:
                    # If knowledge_filters is not a dict (e.g., list of FilterExpr), combine as list if effective_filters is dict
                    # Convert the dict to a list and concatenate
                    effective_filters = cast(Any, [effective_filters, *knowledge_filters])
            else:
                effective_filters = [*effective_filters, *knowledge_filters]
        else:
            effective_filters = knowledge_filters

    return effective_filters


def _convert_documents_to_string(team: Team, docs: List[Union[Dict[str, Any], str]]) -> str:
    if docs is None or len(docs) == 0:
        return ""

    if team.references_format == "yaml":
        import yaml

        return yaml.dump(docs)

    return json.dumps(docs, indent=2)


def _convert_dependencies_to_string(team: Team, context: Dict[str, Any]) -> str:
    """Convert the context dictionary to a string representation.

    Args:
        context: Dictionary containing context data

    Returns:
        String representation of the context, or empty string if conversion fails
    """

    if context is None:
        return ""

    try:
        return json.dumps(context, indent=2, default=str)
    except (TypeError, ValueError, OverflowError) as e:
        log_warning(f"Failed to convert context to JSON: {e}")
        # Attempt a fallback conversion for non-serializable objects
        sanitized_context = {}
        for key, value in context.items():
            try:
                # Try to serialize each value individually
                json.dumps({key: value}, default=str)
                sanitized_context[key] = value
            except Exception as e:
                log_error(f"Failed to serialize to JSON: {e}")
                # If serialization fails, convert to string representation
                sanitized_context[key] = str(value)

        try:
            return json.dumps(sanitized_context, indent=2)
        except Exception as e:
            log_error(f"Failed to convert sanitized context to JSON: {e}")
            return str(context)


# ---------------------------------------------------------------------------
# Deep copy
# ---------------------------------------------------------------------------


def deep_copy(team: Team, *, update: Optional[Dict[str, Any]] = None) -> Team:
    """Create and return a deep copy of this Team, optionally updating fields.

    This creates a fresh Team instance with isolated mutable state while sharing
    heavy resources like database connections and models. Member agents are also
    deep copied to ensure complete isolation.

    Args:
        update: Optional dictionary of fields to override in the new Team.

    Returns:
        Team: A new Team instance with copied state.
    """
    from dataclasses import fields
    from inspect import signature

    # Get the set of valid __init__ parameter names
    init_params = set(signature(team.__class__.__init__).parameters.keys()) - {"self"}

    # Extract the fields to set for the new Team
    fields_for_new_team: Dict[str, Any] = {}

    for f in fields(cast(Any, team)):
        # Skip private fields and fields not accepted by __init__
        if f.name.startswith("_") or f.name not in init_params:
            continue

        field_value = getattr(team, f.name)
        if field_value is not None:
            try:
                fields_for_new_team[f.name] = _deep_copy_field(team, f.name, field_value)
            except Exception as e:
                log_warning(f"Failed to deep copy field '{f.name}': {e}. Using original value.")
                fields_for_new_team[f.name] = field_value

    # Update fields if provided
    if update:
        fields_for_new_team.update(update)

    # Create a new Team
    try:
        new_team = team.__class__(**fields_for_new_team)
        log_debug(f"Created new {team.__class__.__name__}")
        return new_team
    except Exception as e:
        log_error(f"Failed to create deep copy of {team.__class__.__name__}: {e}")
        raise


def _deep_copy_field(team: Team, field_name: str, field_value: Any) -> Any:
    """Helper method to deep copy a field based on its type."""
    from copy import deepcopy

    from pydantic import BaseModel

    # For members, return callable factories by reference; deep copy static lists
    if field_name == "members" and field_value is not None:
        if callable(field_value) and not isinstance(field_value, list):
            return field_value
        copied_members = []
        for member in field_value:
            if hasattr(member, "deep_copy"):
                copied_members.append(member.deep_copy())
            else:
                copied_members.append(member)
        return copied_members

    # For tools, return callable factories by reference; share MCP tools but copy others
    if field_name == "tools" and field_value is not None:
        if callable(field_value) and not isinstance(field_value, list):
            return field_value
        try:
            copied_tools = []
            for tool in field_value:
                try:
                    # Share MCP tools (they maintain server connections)
                    is_mcp_tool = hasattr(type(tool), "__mro__") and any(
                        c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__
                    )
                    if is_mcp_tool:
                        copied_tools.append(tool)
                    else:
                        try:
                            copied_tools.append(deepcopy(tool))
                        except Exception:
                            # Tool can't be deep copied, share by reference
                            copied_tools.append(tool)
                except Exception:
                    # MCP detection failed, share tool by reference to be safe
                    copied_tools.append(tool)
            return copied_tools
        except Exception as e:
            # If entire tools processing fails, log and return original list
            log_warning(f"Failed to process tools for deep copy: {e}")
            return field_value

    # Share heavy resources - these maintain connections/pools that shouldn't be duplicated
    if field_name in (
        "db",
        "model",
        "reasoning_model",
        "knowledge",
        "memory_manager",
        "parser_model",
        "output_model",
        "session_summary_manager",
        "compression_manager",
        "learning",
    ):
        return field_value

    # For compound types, attempt a deep copy
    if isinstance(field_value, (list, dict, set)):
        try:
            return deepcopy(field_value)
        except Exception:
            try:
                return copy(field_value)
            except Exception as e:
                log_warning(f"Failed to copy field: {field_name} - {e}")
                return field_value

    # For pydantic models, attempt a model_copy
    if isinstance(field_value, BaseModel):
        try:
            return field_value.model_copy(deep=True)
        except Exception:
            try:
                return field_value.model_copy(deep=False)
            except Exception as e:
                log_warning(f"Failed to copy field: {field_name} - {e}")
                return field_value

    # For other types, attempt a shallow copy first
    try:
        return copy(field_value)
    except Exception:
        # If copy fails, return as is
        return field_value
