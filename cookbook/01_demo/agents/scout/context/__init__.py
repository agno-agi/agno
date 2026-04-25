"""Context builders for Scout's system prompt."""

from .intent_routing import (
    INTENT_ROUTING,
    INTENT_ROUTING_CONTEXT,
    build_intent_routing,
    load_intent_rules,
)
from .source_registry import (
    SOURCE_REGISTRY,
    SOURCE_REGISTRY_STR,
    build_source_registry,
    format_source_registry,
    load_source_metadata,
)

__all__ = [
    "load_source_metadata",
    "build_source_registry",
    "format_source_registry",
    "SOURCE_REGISTRY",
    "SOURCE_REGISTRY_STR",
    "load_intent_rules",
    "build_intent_routing",
    "INTENT_ROUTING",
    "INTENT_ROUTING_CONTEXT",
]
