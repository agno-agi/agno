"""Adversarial tests for DatabricksSQLTools._validate_read_only_query.

These tests attempt every plausible bypass of the SQL validation logic:
comment injection, string literals containing keywords/semicolons,
CTE abuse, multi-statement tricks, case manipulation, whitespace/encoding
games, and edge cases.
"""

import pytest
from unittest.mock import Mock

from agno.tools.databricks_sql import DatabricksSQLTools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tools() -> DatabricksSQLTools:
    """Return a DatabricksSQLTools with a mock connection (no real DB)."""
    return DatabricksSQLTools(connection=Mock(closed=False))


def _validate(query: str) -> str:
    """Shortcut: call _validate_read_only_query and return cleaned query."""
    return _make_tools()._validate_read_only_query(query)


def _assert_blocked(query: str, expected_msg: str | None = None):
    """Assert the query is rejected by validation."""
    with pytest.raises(ValueError) as exc_info:
        _validate(query)
    if expected_msg is not None:
        assert expected_msg in str(exc_info.value)


def _assert_allowed(query: str) -> str:
    """Assert the query passes validation and return the cleaned query."""
    return _validate(query)


# ===================================================================
# 1. Comment-based bypasses
# ===================================================================

class TestCommentBypasses:
    def test_block_comment_around_mutation_is_stripped(self):
        # The DELETE is inside a comment, so the effective query is SELECT 1
        cleaned = _assert_allowed("/* DELETE FROM t */ SELECT 1")
        assert "DELETE" not in cleaned

    def test_semicolon_inside_block_comment(self):
        # Semicolon is in a comment -- should NOT trigger multi-statement check
        cleaned = _assert_allowed("SELECT /* ; DROP TABLE t; */ 1")
        assert "DROP" not in cleaned

    def test_line_comment_strips_mutation(self):
        cleaned = _assert_allowed("-- DELETE\nSELECT 1")
        assert "DELETE" not in cleaned

    def test_line_comment_at_end(self):
        cleaned = _assert_allowed("SELECT 1 -- DROP TABLE t")
        assert "DROP" not in cleaned

    def test_nested_block_comments_supported(self):
        # Nested block comments are now properly depth-tracked.
        # "/* outer /* inner */ still_comment */ SELECT 1" -> entire comment stripped -> " SELECT 1"
        cleaned = _assert_allowed("/* outer /* inner */ still_comment */ SELECT 1")
        assert "outer" not in cleaned
        assert "inner" not in cleaned
        assert "still_comment" not in cleaned

    def test_block_comment_with_no_close(self):
        # Unterminated block comment: the scanner runs off the end.
        # Depending on what remains after partial stripping, the query is either
        # empty or has no recognizable statement keyword.
        _assert_blocked("/* SELECT 1")
        # Nested unterminated also blocked
        _assert_blocked("/* outer /* inner */ still open")

    def test_only_comments(self):
        _assert_blocked("-- just a comment", "Query cannot be empty")
        _assert_blocked("/* just a comment */", "Query cannot be empty")

    def test_multiple_comments_then_select(self):
        cleaned = _assert_allowed("/* a */ -- b\nSELECT 1")
        assert cleaned.strip().startswith("SELECT")


# ===================================================================
# 2. String-based bypasses
# ===================================================================

class TestStringBypasses:
    def test_semicolon_in_single_quoted_string(self):
        # Semicolon inside a string literal should NOT be treated as statement separator
        _assert_allowed("SELECT ';DELETE FROM t;' FROM t")

    def test_keyword_in_double_quoted_identifier(self):
        _assert_allowed('SELECT "DROP TABLE" FROM t')

    def test_keyword_in_backtick_identifier(self):
        _assert_allowed("SELECT `DROP` FROM t")

    def test_escaped_single_quote(self):
        # SQL standard escapes single quotes by doubling: ''
        _assert_allowed("SELECT 'it''s; DELETE' FROM t")

    def test_escaped_double_quote(self):
        _assert_allowed('SELECT "col""name;DROP" FROM t')

    def test_semicolon_in_backtick_identifier(self):
        _assert_allowed("SELECT `col;DROP` FROM t")

    def test_string_that_looks_like_cte(self):
        _assert_allowed("SELECT 'WITH cte AS (DELETE FROM t)' FROM t")


# ===================================================================
# 3. CTE-based bypasses
# ===================================================================

class TestCTEBypasses:
    def test_cte_with_delete(self):
        _assert_blocked(
            "WITH cte AS (SELECT 1) DELETE FROM t",
            "Only read-only SQL statements are allowed",
        )

    def test_cte_with_insert(self):
        _assert_blocked(
            "WITH cte AS (SELECT 1) INSERT INTO t SELECT * FROM cte",
            "Only read-only SQL statements are allowed",
        )

    def test_cte_with_update(self):
        _assert_blocked(
            "WITH cte AS (SELECT 1) UPDATE t SET x = 1",
            "Only read-only SQL statements are allowed",
        )

    def test_cte_with_merge(self):
        _assert_blocked(
            "WITH cte AS (SELECT 1) MERGE INTO t USING cte ON 1=1 WHEN MATCHED THEN DELETE",
            "Only read-only SQL statements are allowed",
        )

    def test_cte_with_drop(self):
        _assert_blocked(
            "WITH cte AS (SELECT 1) DROP TABLE t",
            "Only read-only SQL statements are allowed",
        )

    def test_cte_with_create(self):
        _assert_blocked(
            "WITH cte AS (SELECT 1) CREATE TABLE t AS SELECT * FROM cte",
            "Only read-only SQL statements are allowed",
        )

    def test_cte_recursive_select(self):
        _assert_allowed(
            "WITH RECURSIVE cte AS (SELECT 1 UNION ALL SELECT n+1 FROM cte WHERE n < 10) SELECT * FROM cte"
        )

    def test_multiple_ctes_select(self):
        _assert_allowed(
            "WITH cte AS (SELECT 1), cte2 AS (SELECT 2) SELECT * FROM cte"
        )

    def test_multiple_ctes_with_delete(self):
        _assert_blocked(
            "WITH cte AS (SELECT 1), cte2 AS (SELECT 2) DELETE FROM t",
            "Only read-only SQL statements are allowed",
        )

    def test_cte_with_column_list(self):
        _assert_allowed(
            "WITH cte(a, b) AS (SELECT 1, 2) SELECT a, b FROM cte"
        )

    def test_deeply_nested_subquery_in_cte(self):
        _assert_allowed(
            "WITH cte AS (SELECT * FROM (SELECT * FROM (SELECT 1))) SELECT * FROM cte"
        )

    def test_cte_body_contains_parens_and_strings(self):
        _assert_allowed(
            "WITH cte AS (SELECT '(' FROM t WHERE x = ')') SELECT * FROM cte"
        )


# ===================================================================
# 4. Multi-statement bypasses
# ===================================================================

class TestMultiStatementBypasses:
    def test_two_selects(self):
        _assert_blocked("SELECT 1; SELECT 2", "Only a single SQL statement is allowed")

    def test_select_then_delete(self):
        _assert_blocked("SELECT 1; DELETE FROM t", "Only a single SQL statement is allowed")

    def test_trailing_semicolon_no_content(self):
        # Trailing semicolon with nothing after should be allowed
        _assert_allowed("SELECT 1;")

    def test_trailing_semicolon_whitespace(self):
        _assert_allowed("SELECT 1;   ")

    def test_trailing_semicolon_newline(self):
        _assert_allowed("SELECT 1;\n")

    def test_trailing_semicolon_tab(self):
        _assert_allowed("SELECT 1;\t")

    def test_double_semicolon(self):
        # Two semicolons imply an empty statement between them -- should be blocked
        _assert_blocked("SELECT 1;;", "Only a single SQL statement is allowed")

    def test_semicolon_whitespace_semicolon(self):
        _assert_blocked("SELECT 1;  ;", "Only a single SQL statement is allowed")

    def test_semicolon_then_comment_then_statement(self):
        _assert_blocked(
            "SELECT 1; -- comment\nDELETE FROM t",
            "Only a single SQL statement is allowed",
        )

    def test_semicolon_inside_string_not_split(self):
        _assert_allowed("SELECT 'a;b' FROM t")

    def test_semicolon_inside_double_quote(self):
        _assert_allowed('SELECT "a;b" FROM t')

    def test_semicolon_inside_backtick(self):
        _assert_allowed("SELECT `a;b` FROM t")


# ===================================================================
# 5. Case manipulation
# ===================================================================

class TestCaseManipulation:
    def test_lowercase_delete(self):
        _assert_blocked("delete from t", "Only read-only SQL statements are allowed")

    def test_mixed_case_delete(self):
        _assert_blocked("DeLeTe FROM t", "Only read-only SQL statements are allowed")

    def test_lowercase_select(self):
        _assert_allowed("select 1")

    def test_mixed_case_select(self):
        _assert_allowed("sElEcT 1")

    def test_uppercase_with_mixed_case_select(self):
        _assert_allowed("WITH cte AS (SELECT 1) sElEcT * FROM cte")

    def test_lowercase_with(self):
        _assert_allowed("with cte as (select 1) select * from cte")

    def test_mixed_case_show(self):
        _assert_allowed("ShOw TABLES")

    def test_mixed_case_describe(self):
        _assert_allowed("dEsCrIbE TABLE t")

    def test_lowercase_drop(self):
        _assert_blocked("drop table t")

    def test_mixed_case_insert(self):
        _assert_blocked("InSeRt INTO t VALUES (1)")

    def test_mixed_case_truncate(self):
        _assert_blocked("tRuNcAtE TABLE t")

    def test_all_blocked_keywords_case_insensitive(self):
        blocked = [
            "INSERT INTO t VALUES (1)",
            "UPDATE t SET x=1",
            "DELETE FROM t",
            "MERGE INTO t USING s ON 1=1",
            "CREATE TABLE t (x INT)",
            "ALTER TABLE t ADD COLUMN y INT",
            "DROP TABLE t",
            "TRUNCATE TABLE t",
            "COPY INTO t FROM 's3://bucket'",
            "GRANT SELECT ON t TO user",
            "REVOKE SELECT ON t FROM user",
            "USE CATALOG main",
            "CALL procedure()",
            "OPTIMIZE t",
            "VACUUM t",
            "REPAIR TABLE t",
        ]
        for q in blocked:
            _assert_blocked(q)
            _assert_blocked(q.lower())


# ===================================================================
# 6. Whitespace / encoding attacks
# ===================================================================

class TestWhitespaceEncoding:
    def test_leading_spaces(self):
        _assert_allowed("   SELECT 1")

    def test_leading_tabs(self):
        _assert_allowed("\tSELECT 1")

    def test_leading_newlines(self):
        _assert_allowed("\n\nSELECT 1")

    def test_leading_mixed_whitespace(self):
        _assert_allowed("\t \n \r\n SELECT 1")

    def test_leading_spaces_before_drop(self):
        _assert_blocked("   DROP TABLE t")

    def test_leading_tabs_before_delete(self):
        _assert_blocked("\tDELETE FROM t")

    def test_unicode_non_breaking_space_before_keyword(self):
        # \u00A0 is a non-breaking space. Python's str.isspace() returns True for it,
        # so strip() will remove it. The validation should still work.
        q = "\u00A0SELECT 1"
        # This might pass or fail depending on how strip() handles it
        # The key question is: does strip() remove \u00A0?
        # Python's str.strip() DOES strip \u00A0, so this should pass.
        _assert_allowed(q)

    def test_zero_width_space_before_drop(self):
        # \u200B is a zero-width space. Python's str.isspace() returns False for it.
        # So strip() will NOT remove it. The scanner should fail to parse it as a keyword.
        q = "\u200BDROP TABLE t"
        # The first char is \u200B which is not alpha/underscore, so read_identifier
        # returns None -> "Could not determine SQL statement type"
        _assert_blocked(q, "Could not determine SQL statement type")

    def test_vertical_tab_before_select(self):
        _assert_allowed("\x0BSELECT 1")

    def test_form_feed_before_select(self):
        _assert_allowed("\x0CSELECT 1")


# ===================================================================
# 7. Edge cases
# ===================================================================

class TestEdgeCases:
    def test_empty_query(self):
        _assert_blocked("", "Query cannot be empty")

    def test_only_whitespace(self):
        _assert_blocked("   ", "Query cannot be empty")

    def test_only_semicolons(self):
        # After strip_sql_comments, we have ";;;"
        # _has_multiple_statements should detect multiple statements
        _assert_blocked(";;;", "Only a single SQL statement is allowed")

    def test_single_semicolon(self):
        # ";" is not empty after strip, but _has_multiple_statements returns True
        # because saw_statement_content is False (no real content found)
        _assert_blocked(";", "Only a single SQL statement is allowed")

    def test_very_long_select(self):
        # 10000 columns
        cols = ", ".join(f"col{i}" for i in range(10000))
        _assert_allowed(f"SELECT {cols} FROM t")

    def test_with_keyword_alone(self):
        # Just "WITH" and nothing else -- should fail to parse CTE
        _assert_blocked("WITH", "Could not determine SQL statement type")

    def test_with_as_no_cte_name(self):
        # "WITH AS (SELECT 1) SELECT 1" -- invalid CTE syntax, no name before AS
        # The scanner reads "AS" as the cte_name identifier, then looks for "(" or "AS"
        # after the cte_name. "AS" is read as cte_name, then scanner looks for next token.
        # Actually: read_identifier gets "AS", then skip_whitespace, peek is "(", so
        # it tries consume_balanced which succeeds on "(SELECT 1)", then looks for ","
        # or reads next keyword. Let's see what happens.
        # After consuming "AS" as cte_name and "(SELECT 1)" as the column-list-looking parens,
        # it then looks for "AS" keyword -- next token is "SELECT" which != "AS".
        # match_keyword("AS") fails, skip_whitespace, peek is "S" (not "("), returns None.
        _assert_blocked("WITH AS (SELECT 1) SELECT 1", "Could not determine SQL statement type")

    def test_backtick_identifier_with_keyword(self):
        _assert_allowed("SELECT `DROP` FROM t")

    def test_backtick_identifier_with_semicolon(self):
        _assert_allowed("SELECT `a;b` FROM t")

    def test_show_keyword(self):
        _assert_allowed("SHOW TABLES")

    def test_show_databases(self):
        _assert_allowed("SHOW DATABASES")

    def test_describe_keyword(self):
        _assert_allowed("DESCRIBE TABLE t")

    def test_desc_keyword(self):
        _assert_allowed("DESC t")

    def test_explain_select(self):
        _assert_allowed("EXPLAIN SELECT 1")

    def test_numeric_start(self):
        # Query starting with a number -- not a valid keyword
        _assert_blocked("123", "Could not determine SQL statement type")

    def test_special_char_start(self):
        _assert_blocked("@SELECT 1", "Could not determine SQL statement type")

    def test_parenthesized_select(self):
        # "(SELECT 1)" -- starts with (, not a keyword
        _assert_blocked("(SELECT 1)", "Could not determine SQL statement type")

    def test_cte_with_max_recursion_numeric_level(self):
        # WITH cte MAX RECURSION LEVEL 10 AS (SELECT 1) SELECT * FROM cte
        # The scanner's read_identifier cannot parse "10" (starts with digit),
        # so it returns None -> cannot determine statement type.
        _assert_blocked(
            "WITH cte MAX RECURSION LEVEL 10 AS (SELECT 1) SELECT * FROM cte",
            "Could not determine SQL statement type",
        )

    def test_cte_with_max_recursion_word_level(self):
        # Use a word identifier for the level value (e.g., a variable name)
        _assert_allowed(
            "WITH cte MAX RECURSION LEVEL ten AS (SELECT 1) SELECT * FROM cte"
        )


# ===================================================================
# 8. EXPLAIN bypasses
# ===================================================================

class TestExplainBypasses:
    def test_explain_select_allowed(self):
        _assert_allowed("EXPLAIN SELECT 1")

    def test_explain_delete_blocked(self):
        # EXPLAIN DELETE FROM t -- now blocked because the inner keyword is a mutation
        with pytest.raises(ValueError, match="read-only"):
            _make_tools()._validate_read_only_query("EXPLAIN DELETE FROM t")

    def test_explain_with_format(self):
        _assert_allowed("EXPLAIN FORMATTED SELECT 1")


# ===================================================================
# 9. Blocked keyword completeness
# ===================================================================

class TestBlockedKeywordCompleteness:
    """Ensure every blocked keyword is actually rejected."""

    @pytest.mark.parametrize("keyword", [
        "INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "ALTER",
        "DROP", "TRUNCATE", "COPY", "GRANT", "REVOKE", "USE",
        "CALL", "OPTIMIZE", "VACUUM", "REPAIR",
    ])
    def test_blocked_keyword_rejected(self, keyword):
        _assert_blocked(f"{keyword} something", "Only read-only SQL statements are allowed")

    @pytest.mark.parametrize("keyword", [
        "INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "ALTER",
        "DROP", "TRUNCATE", "COPY", "GRANT", "REVOKE", "USE",
        "CALL", "OPTIMIZE", "VACUUM", "REPAIR",
    ])
    def test_blocked_keyword_via_cte(self, keyword):
        _assert_blocked(
            f"WITH cte AS (SELECT 1) {keyword} something",
            "Only read-only SQL statements are allowed",
        )


# ===================================================================
# 10. Allowed keyword completeness
# ===================================================================

class TestAllowedKeywords:
    @pytest.mark.parametrize("query", [
        "SELECT 1",
        "SHOW TABLES",
        "DESCRIBE TABLE t",
        "DESC t",
        "EXPLAIN SELECT 1",
        "WITH cte AS (SELECT 1) SELECT * FROM cte",
    ])
    def test_allowed_queries(self, query):
        _assert_allowed(query)


# ===================================================================
# 11. Comment stripping correctness
# ===================================================================

class TestCommentStripping:
    """Directly test _strip_sql_comments for correct behavior."""

    def _strip(self, query: str) -> str:
        return _make_tools()._strip_sql_comments(query)

    def test_line_comment_removed(self):
        result = self._strip("SELECT 1 -- comment")
        assert "comment" not in result
        assert "SELECT 1" in result

    def test_block_comment_removed(self):
        result = self._strip("SELECT /* block */ 1")
        assert "block" not in result

    def test_string_content_preserved(self):
        result = self._strip("SELECT '-- not a comment' FROM t")
        assert "-- not a comment" in result

    def test_double_quote_content_preserved(self):
        result = self._strip('SELECT "/* not a comment */" FROM t')
        assert "/* not a comment */" in result

    def test_backtick_content_preserved(self):
        result = self._strip("SELECT `-- not a comment` FROM t")
        assert "-- not a comment" in result

    def test_block_comment_replaced_with_space(self):
        # Block comments are replaced with a space to avoid token merging
        result = self._strip("SEL/* */ECT 1")
        # Should become "SEL ECT 1" not "SELECT 1"
        assert "SEL" in result and "ECT" in result

    def test_comment_inside_string_not_stripped(self):
        result = self._strip("SELECT '/* still here */' FROM t")
        assert "/* still here */" in result


# ===================================================================
# 12. Multi-statement detection edge cases
# ===================================================================

class TestMultiStatementDetection:
    """Directly test _has_multiple_statements."""

    def _has_multi(self, query: str) -> bool:
        return _make_tools()._has_multiple_statements(query)

    def test_single_statement(self):
        assert not self._has_multi("SELECT 1")

    def test_trailing_semicolon(self):
        assert not self._has_multi("SELECT 1;")

    def test_trailing_semicolon_whitespace(self):
        assert not self._has_multi("SELECT 1;  \n\t")

    def test_two_statements(self):
        assert self._has_multi("SELECT 1; SELECT 2")

    def test_semicolon_in_single_quote(self):
        assert not self._has_multi("SELECT ';' FROM t")

    def test_semicolon_in_double_quote(self):
        assert not self._has_multi('SELECT ";" FROM t')

    def test_semicolon_in_backtick(self):
        assert not self._has_multi("SELECT `;` FROM t")

    def test_empty_between_semicolons(self):
        assert self._has_multi("SELECT 1; ;")

    def test_only_whitespace_no_content(self):
        # No statement content at all -> returns True (no statement found)
        assert self._has_multi("   ")
