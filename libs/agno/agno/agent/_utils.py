"""Shared utility helpers for Agent."""

from __future__ import annotations

import json
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Union,
)

if TYPE_CHECKING:
    from agno.agent.agent import Agent

from agno.filters import FilterExpr
from agno.utils.log import log_debug, log_error, log_warning


def get_effective_filters(
    agent: Agent, knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None
) -> Optional[Any]:
    """
    Determine which knowledge filters to use, with priority to run-level filters.

    Args:
        agent: The Agent instance.
        knowledge_filters: Filters passed at run time.

    Returns:
        The effective filters to use, with run-level filters taking priority.
    """
    effective_filters = None

    # If agent has filters, use those as a base
    if agent.knowledge_filters:
        effective_filters = agent.knowledge_filters.copy()

    # If run has filters, they override agent filters
    if knowledge_filters:
        if effective_filters:
            if isinstance(knowledge_filters, dict):
                if isinstance(effective_filters, dict):
                    effective_filters.update(knowledge_filters)
                else:
                    effective_filters = knowledge_filters
            elif isinstance(knowledge_filters, list):
                effective_filters = [*effective_filters, *knowledge_filters]
        else:
            effective_filters = knowledge_filters

    if effective_filters:
        log_debug(f"Using knowledge filters: {effective_filters}")

    return effective_filters


def convert_documents_to_string(agent: Agent, docs: List[Union[Dict[str, Any], str]]) -> str:
    if docs is None or len(docs) == 0:
        return ""

    if agent.references_format == "yaml":
        import yaml

        return yaml.dump(docs)

    return json.dumps(docs, indent=2, ensure_ascii=False)


def convert_dependencies_to_string(agent: Agent, context: Dict[str, Any]) -> str:
    """Convert the context dictionary to a string representation.

    Args:
        agent: The Agent instance.
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
            except Exception:
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


def deep_copy(agent: Agent, *, update: Optional[Dict[str, Any]] = None) -> Agent:
    """Create and return a deep copy of this Agent, optionally updating fields.

    Args:
        agent: The Agent instance to copy.
        update (Optional[Dict[str, Any]]): Optional dictionary of fields for the new Agent.

    Returns:
        Agent: A new Agent instance.
    """
    from dataclasses import fields
    from inspect import signature

    # Get the set of valid __init__ parameter names
    init_params = set(signature(agent.__class__.__init__).parameters.keys()) - {"self"}

    # Extract the fields to set for the new Agent
    fields_for_new_agent: Dict = {}

    for f in fields(agent):
        # Skip private fields and fields not accepted by __init__
        if f.name.startswith("_") or f.name not in init_params:
            continue

        field_value = getattr(agent, f.name)
        if field_value is not None:
            try:
                fields_for_new_agent[f.name] = deep_copy_field(agent, f.name, field_value)
            except Exception as e:
                log_warning(f"Failed to deep copy field '{f.name}': {e}. Using original value.")
                fields_for_new_agent[f.name] = field_value

    # Update fields if provided
    if update:
        fields_for_new_agent.update(update)

    # Create a new Agent
    try:
        new_agent = agent.__class__(**fields_for_new_agent)
        log_debug(f"Created new {agent.__class__.__name__}")
        return new_agent
    except Exception as e:
        log_error(f"Failed to create deep copy of {agent.__class__.__name__}: {e}")
        raise


def deep_copy_field(agent: Agent, field_name: str, field_value: Any) -> Any:
    """Helper function to deep copy a field based on its type."""
    from copy import copy, deepcopy

    from pydantic import BaseModel

    # For memory and reasoning_agent, use their deep_copy methods
    if field_name == "reasoning_agent":
        return field_value.deep_copy()  # type: ignore

    # For tools, share MCP tools but copy others
    if field_name == "tools" and field_value is not None:
        try:
            copied_tools = []
            for tool in field_value:  # type: ignore
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
        "culture_manager",
        "compression_manager",
        "learning",
        "skills",
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
