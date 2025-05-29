"""
Utility functions for handling JSON schemas across different model providers.
This module provides model-agnostic schema transformations and validations.
"""

from typing import Any, Dict, Type

from pydantic import BaseModel


def is_dict_field(schema: Dict[str, Any]) -> bool:
    """
    Check if a schema represents a Dict[str, T] field.

    Args:
        schema: JSON schema dictionary

    Returns:
        bool: True if the schema represents a Dict field
    """
    return (
        schema.get("type") == "object"
        and "additionalProperties" in schema
        and isinstance(schema["additionalProperties"], dict)
        and "type" in schema["additionalProperties"]
        and "properties" not in schema
    )


def get_dict_value_type(schema: Dict[str, Any]) -> str:
    """
    Extract the value type from a Dict field schema.

    Args:
        schema: JSON schema dictionary for a Dict field

    Returns:
        str: The type of values in the dictionary (e.g., "integer", "string")
    """
    if is_dict_field(schema):
        return schema["additionalProperties"]["type"]
    return "string"


def normalize_schema_for_provider(schema: Dict[str, Any], provider: str) -> Dict[str, Any]:
    """
    Normalize a Pydantic-generated schema for a specific model provider.

    Args:
        schema: Original Pydantic JSON schema
        provider: Model provider name ("openai", "gemini", "anthropic", etc.)

    Returns:
        Dict[str, Any]: Normalized schema for the provider
    """
    # Make a deep copy to avoid modifying the original
    import copy

    normalized = copy.deepcopy(schema)

    if provider.lower() == "openai":
        return _normalize_for_openai(normalized)
    elif provider.lower() == "gemini":
        return _normalize_for_gemini(normalized)
    else:
        # Default normalization for other providers
        return _normalize_generic(normalized)


def _normalize_for_openai(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize schema for OpenAI structured outputs."""
    from agno.utils.models.openai_responses import sanitize_response_schema

    sanitize_response_schema(schema)
    return schema


def _normalize_for_gemini(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize schema for Gemini.
    Gemini has specific requirements for object types and doesn't support
    additionalProperties in the same way as JSON Schema.
    """

    def _process_schema(s: Dict[str, Any]) -> None:
        if isinstance(s, dict):
            # Handle Dict fields - preserve additionalProperties info for convert_schema
            if is_dict_field(s):
                # For Gemini, we need to preserve the additionalProperties info
                # so that convert_schema can create appropriate placeholder properties
                value_type = get_dict_value_type(s)

                # Update description to indicate this is a dictionary
                current_desc = s.get("description", "")
                if current_desc:
                    s["description"] = f"{current_desc} (Dictionary with {value_type} values)"
                else:
                    s["description"] = f"Dictionary with {value_type} values"

                # Keep additionalProperties for convert_schema to process
                # Don't remove it here - let convert_schema handle the conversion

            # Recursively process nested schemas
            for value in s.values():
                if isinstance(value, dict):
                    _process_schema(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            _process_schema(item)

    _process_schema(schema)
    return schema


def _normalize_generic(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Generic normalization for other providers."""

    def _process_schema(s: Dict[str, Any]) -> None:
        if isinstance(s, dict):
            # Remove null defaults
            if "default" in s and s["default"] is None:
                s.pop("default")

            # Recursively process nested schemas
            for value in s.values():
                if isinstance(value, dict):
                    _process_schema(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict):
                            _process_schema(item)

    _process_schema(schema)
    return schema


def get_response_schema_for_provider(response_model: Type[BaseModel], provider: str) -> Dict[str, Any]:
    """
    Get a properly formatted response schema for a specific model provider.

    Args:
        response_model: Pydantic BaseModel class
        provider: Model provider name

    Returns:
        Dict[str, Any]: Provider-specific schema
    """
    # Generate the base schema
    base_schema = response_model.model_json_schema()

    # Normalize for the specific provider
    return normalize_schema_for_provider(base_schema, provider)
