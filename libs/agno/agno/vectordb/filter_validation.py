"""Validation helpers for vector-DB metadata filters.

Metadata filter **keys** are interpolated into backend query strings (Milvus
expression, SurrealQL, N1QL) by several vector-DB backends. Because these keys
are attacker-controlled (they reach the search path from unauthenticated HTTP
and from the agent), an invalid key can inject query syntax and defeat tenant
isolation (agno-agi/agno#8823).

This module centralizes the validation so every backend applies the same rule:
a metadata key must be a simple identifier (letters, digits, underscore). Values
are bound as parameters by the backends that support binding; Milvus builds a
raw expression string, so its string values are escaped here too.
"""

import re
from typing import Any

# A safe metadata key: one or more word characters, nothing else. Matches the
# charset suggested in the issue report (^[A-Za-z0-9_]+$).
_SAFE_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")


class InvalidMetadataKeyError(ValueError):
    """Raised when a metadata filter key is not a safe identifier."""


def validate_metadata_key(key: Any) -> str:
    """Validate that a metadata filter key is safe to interpolate into a query.

    Args:
        key: The metadata key to validate.

    Returns:
        The validated key as a string.

    Raises:
        InvalidMetadataKeyError: If the key is not a string, empty, or contains
            characters outside ``[A-Za-z0-9_]``.
    """
    if not isinstance(key, str):
        raise InvalidMetadataKeyError(f"Metadata key must be a string, got {type(key).__name__}: {key!r}")
    if not key:
        raise InvalidMetadataKeyError("Metadata key must not be empty")
    if not _SAFE_KEY_PATTERN.match(key):
        raise InvalidMetadataKeyError(
            f"Invalid metadata key {key!r}: keys must match [A-Za-z0-9_] (letters, digits, underscore only)"
        )
    return key


def validate_metadata_keys(filters: Any) -> None:
    """Validate every key in a metadata filter mapping.

    Args:
        filters: A dict-like mapping whose keys are validated. No-op for
            ``None`` / empty.

    Raises:
        InvalidMetadataKeyError: If any key fails validation.
    """
    if not filters:
        return
    for key in filters.keys():
        validate_metadata_key(key)


def escape_milvus_string_value(value: str) -> str:
    """Escape a string value for safe embedding inside a Milvus double-quoted literal.

    Milvus ``filter=`` is a raw, server-parsed expression string with no bind
    parameters, so string values are interpolated directly into
    ``meta_data["k"] == "<value>"``. To prevent breaking out of the literal or
    injecting expression operators, backslash-escape the quote and backslash
    characters, and reject values that still contain a newline (which can
    terminate the expression early on some parsers).

    Args:
        value: The raw string value.

    Returns:
        The escaped string, safe to place between double quotes in a Milvus
        expression.
    """
    if not isinstance(value, str):
        raise TypeError(f"escape_milvus_string_value expects str, got {type(value).__name__}")
    # Escape backslash first, then the double quote that delimits the literal.
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    if "\n" in escaped or "\r" in escaped:
        raise ValueError("Milvus string filter values must not contain newlines")
    return escaped
