"""
Bug condition exploration tests for `Clickhouse.delete_by_metadata`.

These tests encode the EXPECTED (fixed) behavior described in
`.kiro/specs/clickhouse-delete-by-metadata-sqli/bugfix.md` and the corresponding
design document. The bug is direct f-string interpolation of caller-supplied
metadata keys and string values into the DELETE WHERE clause in
`libs/agno/agno/vectordb/clickhouse/clickhousedb.py`.

These tests are EXPECTED TO FAIL on the unfixed code (failure confirms the bug
exists). They will PASS once the fix is in place — that is, once every metadata
key and value is bound as a typed ClickHouse named parameter and unsafe keys
are rejected with `ValueError` before any SQL is issued.

Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.2, 2.3
"""

from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from agno.vectordb.clickhouse import Clickhouse

# ---------------------------------------------------------------------------
# SQL meta-characters that the bug condition treats as injection signals.
# Mirrors `containsSqlMetaCharacter` from the design document.
# ---------------------------------------------------------------------------
SQL_META_CHARS: Tuple[str, ...] = ("'", "\\", ";", "--", "/*", "*/")


def _contains_sql_meta(s: str) -> bool:
    return any(meta in s for meta in SQL_META_CHARS)


# ---------------------------------------------------------------------------
# Helpers to build a Clickhouse with a mocked client that records every
# `client.command(...)` invocation as `(sql_text, parameters_dict)` tuples.
# ---------------------------------------------------------------------------
def _make_clickhouse() -> Tuple[Clickhouse, MagicMock, List[Tuple[str, Dict[str, Any]]]]:
    """Construct a Clickhouse instance backed by a recording mock client.

    Returns:
        (clickhouse_instance, mock_client, command_calls)
        where `command_calls` is a list of (sql_text, parameters_dict) captured
        from every call to `mock_client.command(...)`.
    """
    captured: List[Tuple[str, Dict[str, Any]]] = []

    mock_client = MagicMock()

    def _record_command(sql_text: str, parameters: Optional[Dict[str, Any]] = None, *args, **kwargs):
        # Defensive copy so later mutations of `parameters` don't poison capture.
        captured.append((sql_text, dict(parameters) if parameters is not None else {}))
        return None

    mock_client.command.side_effect = _record_command

    mock_embedder = MagicMock()
    mock_embedder.dimensions = 1024

    with patch("clickhouse_connect.get_client", return_value=mock_client):
        db = Clickhouse(
            table_name="test_table",
            host="localhost",
            database_name="test_db",
            embedder=mock_embedder,
            client=mock_client,
        )

    return db, mock_client, captured


# ---------------------------------------------------------------------------
# Concrete deterministic cases (Property 1: Bug Condition)
# Each case asserts the FIXED behavior. On the UNFIXED code these MUST FAIL.
# ---------------------------------------------------------------------------


def test_value_with_sql_tautology_is_parameterized_not_interpolated():
    """Value injection: ``{"source": "' OR '1'='1"}``.

    On the fixed code the value MUST appear only in `parameters=`, never as a
    literal substring of the SQL text.

    Validates: Requirements 1.1, 2.1
    """
    db, mock_client, captured = _make_clickhouse()

    result = db.delete_by_metadata({"source": "' OR '1'='1"})

    assert result is True, "fixed code must return True for safe-key + str value"
    assert len(captured) == 1, "client.command must be invoked exactly once"
    sql_text, parameters = captured[0]

    assert "' OR '1'='1" not in sql_text, (
        f"value must not be interpolated into SQL text; expected parameter binding. SQL was: {sql_text!r}"
    )
    assert parameters.get("v_0") == "' OR '1'='1", (
        f"value must be bound as parameter v_0; parameters were: {parameters!r}"
    )


def test_unsafe_key_raises_value_error_and_does_not_invoke_command():
    """Key injection: ``{"x') = '1' OR ('1": "1"}``.

    On the fixed code the unsafe key MUST be rejected with `ValueError` BEFORE
    any DELETE statement is issued.

    Validates: Requirements 1.2, 2.2
    """
    db, mock_client, captured = _make_clickhouse()

    with pytest.raises(ValueError):
        db.delete_by_metadata({"x') = '1' OR ('1": "1"})

    assert mock_client.command.call_count == 0, "client.command must NEVER be invoked when a key fails the safe regex"
    assert captured == [], "no SQL must be captured for an unsafe-key call"


def test_value_with_unbalanced_quote_is_parameterized_and_not_swallowed():
    """Single-quote in value: ``{"author": "O'Brien"}``.

    On the unfixed code this produces malformed SQL (`= 'O'Brien'`) and the
    broad `except Exception` swallows the ClickHouse parse error so the method
    returns False. On the fixed code the value is bound as a parameter, no
    parse error occurs, and the call returns True.

    Validates: Requirements 1.3, 2.3
    """
    db, mock_client, captured = _make_clickhouse()

    result = db.delete_by_metadata({"author": "O'Brien"})

    assert result is True, (
        "fixed code must return True; the broad-exception path must not be"
        " triggered for a legitimate single-quote-in-value input"
    )
    assert len(captured) == 1, "client.command must be invoked exactly once"
    sql_text, parameters = captured[0]

    assert "= 'O'Brien'" not in sql_text, "fixed SQL must not contain the malformed literal '= \\'O\\'Brien\\''"
    assert "O'Brien" not in sql_text, (
        f"fixed SQL must not contain the value as a literal substring; SQL was: {sql_text!r}"
    )
    assert parameters.get("v_0") == "O'Brien", f"value must be bound as parameter v_0; parameters were: {parameters!r}"


def test_value_with_trailing_backslash_is_parameterized():
    """Value with trailing backslash: ``{"path": "C:\\\\"}`` (Python literal
    ``"C:\\"``, i.e. ``C:`` followed by one backslash).

    On the unfixed code the trailing backslash either rewrites the predicate or
    triggers a parse error. On the fixed code the value is bound verbatim as a
    `String` parameter.

    Validates: Requirements 2.1, 2.3
    """
    db, mock_client, captured = _make_clickhouse()

    result = db.delete_by_metadata({"path": "C:\\"})

    assert result is True
    assert len(captured) == 1
    sql_text, parameters = captured[0]

    assert "C:\\" not in sql_text, f"fixed SQL must not contain the value as a literal substring; SQL was: {sql_text!r}"
    assert parameters.get("v_0") == "C:\\", (
        f"value must be bound verbatim as parameter v_0; parameters were: {parameters!r}"
    )


# ---------------------------------------------------------------------------
# Property-based tests (Hypothesis)
# ---------------------------------------------------------------------------


# A printable-text strategy with each generated string forced to contain at
# least one SQL meta-character. This keeps generation deterministic and
# focused on the bug condition.
_meta_char_st = st.sampled_from(SQL_META_CHARS)
_filler_text_st = st.text(
    alphabet=st.characters(
        # Limit to printable Latin letters/digits/symbols so the literal
        # substring check is unambiguous.
        min_codepoint=0x20,
        max_codepoint=0x7E,
    ),
    max_size=20,
)


@st.composite
def _str_value_with_sql_meta(draw) -> str:
    prefix = draw(_filler_text_st)
    meta = draw(_meta_char_st)
    suffix = draw(_filler_text_st)
    return prefix + meta + suffix


# Safe identifier-shaped key (matches the JSON-path safe regex from the spec).
_safe_key_st = st.from_regex(r"\A[A-Za-z_][A-Za-z0-9_]{0,15}\Z", fullmatch=True)


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(key=_safe_key_st, value=_str_value_with_sql_meta())
def test_pbt_string_values_with_sql_meta_chars_are_never_interpolated(key: str, value: str):
    """For arbitrary safe keys and any string value containing at least one SQL
    meta-character, the value MUST appear only in `parameters=`, never as a
    literal substring of the emitted SQL text. The call MUST return True.

    Validates: Requirements 2.1, 2.3
    """
    db, mock_client, captured = _make_clickhouse()

    result = db.delete_by_metadata({key: value})

    assert result is True
    assert len(captured) == 1
    sql_text, parameters = captured[0]

    assert value not in sql_text, (
        f"value must not appear as a literal substring of the emitted SQL; key={key!r} value={value!r} sql={sql_text!r}"
    )
    assert parameters.get("v_0") == value, f"value must be bound as parameter v_0; parameters={parameters!r}"


# Unsafe-key strategy — covers empty strings, leading-digit names, whitespace,
# and explicit injection meta-characters. We post-filter to guarantee the
# generated key is genuinely unsafe (does not match the safe-key regex).
_SAFE_KEY_RE_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$"


def _is_unsafe_key(s: str) -> bool:
    import re as _re

    return _re.match(_SAFE_KEY_RE_PATTERN, s) is None


_unsafe_key_st = st.one_of(
    st.just(""),  # empty
    st.from_regex(r"\A[0-9][A-Za-z0-9_]*\Z", fullmatch=True),  # leading digit
    st.from_regex(r"\A[A-Za-z_]+ [A-Za-z_]+\Z", fullmatch=True),  # contains space
    st.from_regex(r"\A.*['();].*\Z", fullmatch=True),  # contains injection chars
    st.from_regex(r"\A.*--.*\Z", fullmatch=True),  # contains SQL comment marker
).filter(_is_unsafe_key)


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much])
@given(unsafe_key=_unsafe_key_st)
def test_pbt_unsafe_keys_always_raise_value_error(unsafe_key: str):
    """For arbitrary keys that fail the safe JSON-path regex,
    `delete_by_metadata` MUST raise `ValueError` and MUST NOT invoke
    `client.command`.

    Validates: Requirement 2.2
    """
    db, mock_client, captured = _make_clickhouse()

    with pytest.raises(ValueError):
        db.delete_by_metadata({unsafe_key: "1"})

    assert mock_client.command.call_count == 0, f"client.command must not be invoked for unsafe key {unsafe_key!r}"
    assert captured == [], f"no SQL must be captured for unsafe key {unsafe_key!r}"
