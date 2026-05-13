"""
Preservation tests for `Clickhouse.delete_by_metadata`.

These tests encode the BASELINE behavior that must be preserved across the
SQL-injection fix described in
`.kiro/specs/clickhouse-delete-by-metadata-sqli/`.

Methodology (observation-first):

- All assertions encode behavior observed on the UNFIXED code AND known to
  remain stable on the FIXED code. They MUST pass on the unfixed code, and
  they MUST continue to pass after the fix in Task 3 is applied.
- For inputs whose SQL text differs between unfixed (literal interpolation)
  and fixed (named-parameter binding), only observable post-conditions that
  are stable across both implementations are asserted: return value,
  ``client.command`` invocation count, ``JSONExtract*`` function selection,
  the `` AND ``-join structure, and the presence of ``log_debug`` /
  ``log_info`` calls. The exact emitted SQL string is intentionally NOT
  asserted in these preservation tests.

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8
"""

import inspect
from typing import Any, Dict, List, Optional, Tuple, Union
from unittest.mock import MagicMock, patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from agno.vectordb.clickhouse import Clickhouse

# ---------------------------------------------------------------------------
# Constants - mirror design.md
# ---------------------------------------------------------------------------
SQL_META_CHARS: Tuple[str, ...] = ("'", "\\", ";", "--", "/*", "*/")


def _count_jsonextract(sql_text: str) -> int:
    """Number of ``JSONExtract{String,Float,Bool}`` calls emitted in ``sql_text``."""
    return sql_text.count("JSONExtractString") + sql_text.count("JSONExtractFloat") + sql_text.count("JSONExtractBool")


# ---------------------------------------------------------------------------
# Mock client helpers
# ---------------------------------------------------------------------------
def _make_clickhouse() -> Tuple[Clickhouse, MagicMock, List[Tuple[str, Dict[str, Any]]]]:
    """Construct a Clickhouse instance backed by a recording mock client.

    Returns:
        (clickhouse_instance, mock_client, command_calls)
        where ``command_calls`` is the list of ``(sql_text, parameters_dict)``
        tuples captured from every call to ``mock_client.command(...)``.
    """
    captured: List[Tuple[str, Dict[str, Any]]] = []

    mock_client = MagicMock()

    def _record_command(sql_text: str, parameters: Optional[Dict[str, Any]] = None, *args, **kwargs):
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


def _make_clickhouse_with_raising_client(exc: Exception) -> Tuple[Clickhouse, MagicMock]:
    """Construct a Clickhouse instance whose mock ``client.command`` raises ``exc``."""
    mock_client = MagicMock()
    mock_client.command.side_effect = exc

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

    return db, mock_client


# ---------------------------------------------------------------------------
# Concrete observation cases
# Each asserts the OBSERVED behavior on the UNFIXED code that the FIXED code
# must preserve.
# ---------------------------------------------------------------------------


def test_signature_unchanged():
    """The public method signature must remain
    ``delete_by_metadata(self, metadata: Dict[str, Any]) -> bool``.

    Validates: Requirement 3.8
    """
    sig = inspect.signature(Clickhouse.delete_by_metadata)
    params = list(sig.parameters.values())

    assert [p.name for p in params] == ["self", "metadata"], f"unexpected parameters: {[p.name for p in params]!r}"
    assert sig.return_annotation is bool, f"unexpected return annotation: {sig.return_annotation!r}"

    metadata_param = sig.parameters["metadata"]
    # Annotation may be a typing.Dict[str, Any] generic alias; just sanity-check it
    # references Dict and Any in its repr — implementation detail of typing varies
    # by Python version, so be tolerant here.
    annotation_repr = repr(metadata_param.annotation)
    assert "Dict" in annotation_repr or "dict" in annotation_repr, (
        f"metadata annotation should be a Dict; got {annotation_repr!r}"
    )


def test_log_debug_called_once_at_method_entry_for_success_path():
    """``log_debug`` is called exactly once at method entry with the
    documented format string. This holds for unfixed and fixed code.

    Validates: Requirement 3.8
    """
    db, _mock_client, _captured = _make_clickhouse()

    metadata = {"category": "tech"}
    with patch("agno.vectordb.clickhouse.clickhousedb.log_debug") as mock_log_debug:
        result = db.delete_by_metadata(metadata)

    assert result is True
    assert mock_log_debug.call_count == 1, (
        f"log_debug must be called exactly once; was called {mock_log_debug.call_count} times"
    )
    (call_args, _call_kwargs) = mock_log_debug.call_args
    assert call_args == (f"ClickHouse VectorDB : Deleting documents with metadata {metadata}",), (
        f"unexpected log_debug message: {call_args!r}"
    )


def test_log_debug_called_once_at_method_entry_for_empty_dict():
    """``log_debug`` is called exactly once at method entry even when the
    metadata dict is empty (the early-return path).

    Validates: Requirement 3.8
    """
    db, mock_client, _captured = _make_clickhouse()

    with patch("agno.vectordb.clickhouse.clickhousedb.log_debug") as mock_log_debug:
        result = db.delete_by_metadata({})

    assert result is False
    assert mock_log_debug.call_count == 1
    assert mock_client.command.call_count == 0


def test_string_value_uses_jsonextractstring_and_returns_true():
    """``delete_by_metadata({"category": "tech"})`` returns True; the SQL
    uses ``JSONExtractString``.

    Validates: Requirements 3.1, 3.5
    """
    db, _mock_client, captured = _make_clickhouse()

    result = db.delete_by_metadata({"category": "tech"})

    assert result is True
    assert len(captured) == 1
    sql_text, _params = captured[0]
    assert "JSONExtractString" in sql_text
    assert _count_jsonextract(sql_text) == 1


def test_int_value_uses_jsonextractfloat_and_returns_true():
    """``delete_by_metadata({"year": 2024})`` returns True; SQL uses
    ``JSONExtractFloat``.

    Validates: Requirement 3.2
    """
    db, _mock_client, captured = _make_clickhouse()

    result = db.delete_by_metadata({"year": 2024})

    assert result is True
    assert len(captured) == 1
    sql_text, _params = captured[0]
    assert "JSONExtractFloat" in sql_text
    assert "JSONExtractBool" not in sql_text
    assert "JSONExtractString" not in sql_text


def test_float_value_uses_jsonextractfloat_and_returns_true():
    """``delete_by_metadata({"score": 0.5})`` returns True; SQL uses
    ``JSONExtractFloat``.

    Validates: Requirement 3.2
    """
    db, _mock_client, captured = _make_clickhouse()

    result = db.delete_by_metadata({"score": 0.5})

    assert result is True
    assert len(captured) == 1
    sql_text, _params = captured[0]
    assert "JSONExtractFloat" in sql_text
    assert "JSONExtractBool" not in sql_text


def test_bool_value_uses_jsonextractbool_dispatched_before_int_float():
    """``delete_by_metadata({"published": True})`` returns True; SQL uses
    ``JSONExtractBool`` (``bool`` is dispatched BEFORE the ``int``/``float``
    branch, since ``bool`` is a subclass of ``int`` in Python).

    Validates: Requirement 3.3
    """
    db, _mock_client, captured = _make_clickhouse()

    result = db.delete_by_metadata({"published": True})

    assert result is True
    assert len(captured) == 1
    sql_text, _params = captured[0]
    assert "JSONExtractBool" in sql_text, "bool must dispatch to JSONExtractBool, not JSONExtractFloat"
    assert "JSONExtractFloat" not in sql_text


def test_multi_key_dict_emits_and_combined_conditions():
    """``delete_by_metadata({"category": "tech", "year": 2024})`` returns True;
    the SQL has both conditions joined by `` AND ``.

    Validates: Requirement 3.4
    """
    db, _mock_client, captured = _make_clickhouse()

    result = db.delete_by_metadata({"category": "tech", "year": 2024})

    assert result is True
    assert len(captured) == 1
    sql_text, _params = captured[0]
    # Exactly one condition per dict entry, joined with " AND "
    assert _count_jsonextract(sql_text) == 2
    assert " AND " in sql_text
    # And both function selections are present
    assert "JSONExtractString" in sql_text
    assert "JSONExtractFloat" in sql_text


def test_empty_dict_returns_false_and_command_never_called():
    """``delete_by_metadata({})`` returns False and ``client.command`` is
    NEVER called.

    Validates: Requirement 3.6
    """
    db, mock_client, captured = _make_clickhouse()

    result = db.delete_by_metadata({})

    assert result is False
    assert mock_client.command.call_count == 0
    assert captured == []


def test_unexpected_client_exception_returns_false_and_logs_info():
    """When ``client.command`` raises an unexpected exception, the method
    returns False and ``log_info`` is called once with a message containing
    the exception text and the metadata representation.

    Validates: Requirement 3.7
    """
    metadata = {"k": "v"}
    db, mock_client = _make_clickhouse_with_raising_client(Exception("boom"))

    with patch("agno.vectordb.clickhouse.clickhousedb.log_info") as mock_log_info:
        result = db.delete_by_metadata(metadata)

    assert result is False
    assert mock_client.command.call_count == 1
    assert mock_log_info.call_count == 1, (
        f"log_info must be called exactly once on unexpected exception; was called {mock_log_info.call_count} times"
    )
    (log_args, _log_kwargs) = mock_log_info.call_args
    assert len(log_args) == 1
    log_message = log_args[0]
    assert "boom" in log_message, f"log_info message should contain 'boom'; got {log_message!r}"
    assert repr(metadata) in log_message or str(metadata) in log_message, (
        f"log_info message should contain the metadata repr/str; got {log_message!r}"
    )


# ---------------------------------------------------------------------------
# Property-based tests (Hypothesis)
#
# These properties encode behavior that is stable on BOTH the unfixed and the
# fixed code: return value, command-invocation count, JSONExtract* function
# selection, and `` AND ``-join structure. The exact SQL text differs between
# the two implementations (literal interpolation vs named-parameter binding),
# so it is intentionally not asserted here.
# ---------------------------------------------------------------------------


# Safe identifier-shaped key (matches the JSON-path safe regex from the spec).
_safe_key_st = st.from_regex(r"\A[A-Za-z_][A-Za-z0-9_]{0,15}\Z", fullmatch=True)


# String value strategy that excludes every SQL meta-character listed in
# the design (single quote, backslash, semicolon, dash, slash, star). This
# guarantees the value cannot break out of the f-string-interpolated form
# used by the UNFIXED code and is therefore safe to compare across both
# implementations.
_safe_str_value_st = st.text(
    alphabet=st.characters(
        min_codepoint=0x20,
        max_codepoint=0x7E,
        blacklist_characters="'\\;-/*",
    ),
    max_size=20,
)


# Mixed-type value strategy for the safe-input property.
_safe_mixed_value_st = st.one_of(
    _safe_str_value_st,
    st.integers(min_value=-1_000_000, max_value=1_000_000),
    st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
    st.booleans(),
)


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    metadata=st.dictionaries(
        keys=_safe_key_st,
        values=_safe_mixed_value_st,
        min_size=1,
        max_size=5,
    )
)
def test_pbt_safe_inputs_preserve_original_behavior(metadata: Dict[str, Any]):
    """For any dict whose keys match the safe JSON-path regex and whose
    string values exclude SQL meta-characters, the observable post-conditions
    must match the recorded baseline:

    - ``return_value == True``
    - ``client.command`` is invoked exactly once
    - the number of emitted conditions equals ``len(metadata)`` (one
      ``JSONExtract*`` call per entry)

    The exact SQL text is intentionally not compared because it differs
    between the unfixed and fixed implementations.

    Validates: Requirements 3.1, 3.2, 3.3, 3.5
    """
    db, _mock_client, captured = _make_clickhouse()

    result = db.delete_by_metadata(metadata)

    assert result is True
    assert len(captured) == 1
    sql_text, _params = captured[0]
    assert _count_jsonextract(sql_text) == len(metadata), (
        f"expected one JSONExtract* call per dict entry; metadata={metadata!r} sql={sql_text!r}"
    )


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(key=_safe_key_st, value=st.booleans())
def test_pbt_bool_dispatched_before_int_float(key: str, value: bool):
    """For ``bool`` values the emitted SQL MUST use ``JSONExtractBool`` and
    MUST NOT use ``JSONExtractFloat``. Since ``bool`` is a subclass of
    ``int`` in Python, this guards against silent coercion to ``1.0`` /
    ``0.0`` via the int/float branch.

    The exact bound-parameter form differs between unfixed (literal
    ``true``/``false`` in the SQL) and fixed (a ``Bool``-typed parameter),
    so only the ``JSONExtractBool`` selection is asserted here.

    Validates: Requirement 3.3
    """
    db, _mock_client, captured = _make_clickhouse()

    result = db.delete_by_metadata({key: value})

    assert result is True
    assert len(captured) == 1
    sql_text, _params = captured[0]
    assert "JSONExtractBool" in sql_text, (
        f"bool value must dispatch to JSONExtractBool; key={key!r} value={value!r} sql={sql_text!r}"
    )
    assert "JSONExtractFloat" not in sql_text, (
        f"bool must not dispatch to JSONExtractFloat; key={key!r} value={value!r} sql={sql_text!r}"
    )


# A non-bool numeric value: int (excluding True/False) or finite float.
_non_bool_numeric_st = st.one_of(
    st.integers(min_value=-1_000_000, max_value=1_000_000),
    st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
).filter(lambda v: not isinstance(v, bool))


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(key=_safe_key_st, value=_non_bool_numeric_st)
def test_pbt_int_float_use_jsonextractfloat(key: str, value: Union[int, float]):
    """For ``int`` (excluding ``bool``) and ``float`` values, the emitted
    SQL MUST use ``JSONExtractFloat``.

    Validates: Requirement 3.2
    """
    # Sanity guard: the strategy must never produce a bool here.
    assert not isinstance(value, bool)

    db, _mock_client, captured = _make_clickhouse()

    result = db.delete_by_metadata({key: value})

    assert result is True
    assert len(captured) == 1
    sql_text, _params = captured[0]
    assert "JSONExtractFloat" in sql_text, (
        f"int/float must dispatch to JSONExtractFloat; key={key!r} value={value!r} sql={sql_text!r}"
    )


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    metadata=st.dictionaries(
        keys=_safe_key_st,
        values=_safe_mixed_value_st,
        min_size=2,
        max_size=5,
    )
)
def test_pbt_and_combined_matching_preserved(metadata: Dict[str, Any]):
    """For dicts of size >= 2 with mixed value types, the emitted SQL MUST:

    - join all conditions with `` AND `` (so the operator appears exactly
      ``len(metadata) - 1`` times),
    - emit exactly one ``JSONExtract*`` call per dict entry.

    Validates: Requirement 3.4
    """
    db, _mock_client, captured = _make_clickhouse()

    result = db.delete_by_metadata(metadata)

    assert result is True
    assert len(captured) == 1
    sql_text, _params = captured[0]

    n = len(metadata)
    assert _count_jsonextract(sql_text) == n, (
        f"expected exactly {n} JSONExtract* calls; metadata={metadata!r} sql={sql_text!r}"
    )
    assert sql_text.count(" AND ") == n - 1, (
        f"expected exactly {n - 1} ' AND ' separators; metadata={metadata!r} sql={sql_text!r}"
    )


def test_pbt_empty_dict_returns_false_no_command():
    """For the single input ``{}``, ``delete_by_metadata`` MUST return
    ``False`` and ``client.command`` MUST NEVER be invoked.

    This is encoded as a property over the (degenerate) single-element
    domain ``{ {} }`` so it sits alongside the other PBT entries.

    Validates: Requirement 3.6
    """
    db, mock_client, captured = _make_clickhouse()

    result = db.delete_by_metadata({})

    assert result is False
    assert mock_client.command.call_count == 0
    assert captured == []
