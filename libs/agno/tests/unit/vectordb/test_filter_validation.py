"""Tests for vectordb metadata filter validation (issue #8823).

These cover the shared validation helpers used by every vector-DB backend to
prevent filter-key / value injection. Pure functions — no SDK required.
"""

import pytest

from agno.vectordb.filter_validation import (
    InvalidMetadataKeyError,
    escape_milvus_string_value,
    validate_metadata_key,
    validate_metadata_keys,
)


# --- validate_metadata_key ---


@pytest.mark.parametrize("key", ["category", "linked_to", "user_id_1", "a", "ABC123", "_underscore"])
def test_valid_keys_accepted(key):
    assert validate_metadata_key(key) == key


@pytest.mark.parametrize(
    "key",
    [
        "",  # empty
        "x = 1 OR true //",  # SurrealDB injection
        "x IS NOT NULL OR 1=1 --",  # Couchbase/N1QL injection
        'category" or meta_data["linked_to"] != "zzz',  # Milvus value injection
        "a.b",  # dot (SurrealQL path)
        "with space",
        "dash-key",
        "semi;colon",
        "http::get('http://listener/')",  # SurrealDB SSRF
        "$param",
        "col; DROP TABLE",
    ],
)
def test_invalid_keys_rejected(key):
    with pytest.raises(InvalidMetadataKeyError):
        validate_metadata_key(key)


def test_non_string_key_rejected():
    with pytest.raises(InvalidMetadataKeyError):
        validate_metadata_key(123)  # type: ignore[arg-type]
    with pytest.raises(InvalidMetadataKeyError):
        validate_metadata_key(None)  # type: ignore[arg-type]


# --- validate_metadata_keys ---


def test_validate_metadata_keys_passes_clean_dict():
    validate_metadata_keys({"a": 1, "b": 2, "linked_to": "x"})  # no raise


def test_validate_metadata_keys_rejects_any_bad_key():
    with pytest.raises(InvalidMetadataKeyError):
        validate_metadata_keys({"ok": 1, "bad key": 2})


def test_validate_metadata_keys_noop_on_none_or_empty():
    validate_metadata_keys(None)
    validate_metadata_keys({})


# --- escape_milvus_string_value ---


def test_escape_plain_value_unchanged():
    assert escape_milvus_string_value("alpha") == "alpha"


def test_escape_escapes_double_quote():
    # The issue's PoC value: alpha" or meta_data["linked_to"] != "zzz or "z" == "
    raw = 'alpha" or meta_data["linked_to"] != "zzz or "z" == "'
    escaped = escape_milvus_string_value(raw)
    # Every double quote must be preceded by a backslash so it cannot close the
    # literal in the Milvus expression meta_data["k"] == "<escaped>".
    assert all((i == 0 or escaped[i - 1] == "\\") for i, c in enumerate(escaped) if c == '"')
    assert '\\"' in escaped


def test_escape_escapes_backslash():
    assert escape_milvus_string_value("a\\b") == "a\\\\b"


def test_escape_rejects_newlines():
    with pytest.raises(ValueError):
        escape_milvus_string_value("line\nbreak")
    with pytest.raises(ValueError):
        escape_milvus_string_value("carriage\rreturn")


def test_escape_rejects_non_string():
    with pytest.raises(TypeError):
        escape_milvus_string_value(123)  # type: ignore[arg-type]
