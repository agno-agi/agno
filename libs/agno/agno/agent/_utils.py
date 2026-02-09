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
