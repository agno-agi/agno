"""Unit tests for search filter expressions.

Tests cover:
- Basic filter operators (EQ, IN, GT, LT, NEQ, GTE, LTE)
- String matching operators (CONTAINS, STARTSWITH)
- Logical operators (AND, OR, NOT)
- Operator overloading (&, |, ~)
- Serialization (to_dict)
- Deserialization (from_dict)
- Complex nested expressions
- Edge cases
"""

import pytest

from agno.filters import (
    AND,
    CONTAINS,
    EQ,
    GT,
    GTE,
    IN,
    LT,
    LTE,
    NEQ,
    NOT,
    OR,
    STARTSWITH,
    FilterExpr,
    from_dict,
)


class TestBasicOperators:
    """Test basic filter operators."""

    def test_eq_with_string(self):
        """Test EQ operator with string values."""
        filter_expr = EQ("status", "published")
        assert filter_expr.key == "status"
        assert filter_expr.value == "published"
        assert filter_expr.to_dict() == {
            "op": "EQ",
            "key": "status",
            "value": "published",
        }

    def test_eq_with_int(self):
        """Test EQ operator with integer values."""
        filter_expr = EQ("age", 25)
        assert filter_expr.key == "age"
        assert filter_expr.value == 25
        assert filter_expr.to_dict() == {"op": "EQ", "key": "age", "value": 25}

    def test_eq_with_float(self):
        """Test EQ operator with float values."""
        filter_expr = EQ("price", 19.99)
        assert filter_expr.key == "price"
        assert filter_expr.value == 19.99
        assert filter_expr.to_dict() == {"op": "EQ", "key": "price", "value": 19.99}

    def test_eq_with_bool(self):
        """Test EQ operator with boolean values."""
        filter_expr = EQ("is_active", True)
        assert filter_expr.key == "is_active"
        assert filter_expr.value is True
        assert filter_expr.to_dict() == {"op": "EQ", "key": "is_active", "value": True}

    def test_eq_with_none(self):
        """Test EQ operator with None value."""
        filter_expr = EQ("deleted_at", None)
        assert filter_expr.key == "deleted_at"
        assert filter_expr.value is None
        assert filter_expr.to_dict() == {"op": "EQ", "key": "deleted_at", "value": None}

    def test_in_with_strings(self):
        """Test IN operator with list of strings."""
        filter_expr = IN("category", ["tech", "science", "engineering"])
        assert filter_expr.key == "category"
        assert filter_expr.values == ["tech", "science", "engineering"]
        assert filter_expr.to_dict() == {
            "op": "IN",
            "key": "category",
            "values": ["tech", "science", "engineering"],
        }

    def test_in_with_ints(self):
        """Test IN operator with list of integers."""
        filter_expr = IN("user_id", [1, 2, 3, 100])
        assert filter_expr.key == "user_id"
        assert filter_expr.values == [1, 2, 3, 100]
        assert filter_expr.to_dict() == {
            "op": "IN",
            "key": "user_id",
            "values": [1, 2, 3, 100],
        }

    def test_in_with_empty_list(self):
        """Test IN operator with empty list."""
        filter_expr = IN("tags", [])
        assert filter_expr.key == "tags"
        assert filter_expr.values == []
        assert filter_expr.to_dict() == {"op": "IN", "key": "tags", "values": []}

    def test_in_with_single_item(self):
        """Test IN operator with single item list."""
        filter_expr = IN("status", ["published"])
        assert filter_expr.values == ["published"]

    def test_gt_with_int(self):
        """Test GT operator with integer."""
        filter_expr = GT("age", 18)
        assert filter_expr.key == "age"
        assert filter_expr.value == 18
        assert filter_expr.to_dict() == {"op": "GT", "key": "age", "value": 18}

    def test_gt_with_float(self):
        """Test GT operator with float."""
        filter_expr = GT("score", 85.5)
        assert filter_expr.key == "score"
        assert filter_expr.value == 85.5
        assert filter_expr.to_dict() == {"op": "GT", "key": "score", "value": 85.5}

    def test_gt_with_negative(self):
        """Test GT operator with negative number."""
        filter_expr = GT("temperature", -10)
        assert filter_expr.value == -10

    def test_lt_with_int(self):
        """Test LT operator with integer."""
        filter_expr = LT("age", 65)
        assert filter_expr.key == "age"
        assert filter_expr.value == 65
        assert filter_expr.to_dict() == {"op": "LT", "key": "age", "value": 65}

    def test_lt_with_float(self):
        """Test LT operator with float."""
        filter_expr = LT("price", 100.50)
        assert filter_expr.key == "price"
        assert filter_expr.value == 100.50
        assert filter_expr.to_dict() == {"op": "LT", "key": "price", "value": 100.50}

    def test_lt_with_zero(self):
        """Test LT operator with zero."""
        filter_expr = LT("balance", 0)
        assert filter_expr.value == 0


class TestNewComparisonOperators:
    """Test new comparison operators (NEQ, GTE, LTE)."""

    def test_neq_with_string(self):
        """Test NEQ operator with string values."""
        filter_expr = NEQ("status", "archived")
        assert filter_expr.key == "status"
        assert filter_expr.value == "archived"
        assert filter_expr.to_dict() == {
            "op": "NEQ",
            "key": "status",
            "value": "archived",
        }

    def test_neq_with_int(self):
        """Test NEQ operator with integer values."""
        filter_expr = NEQ("priority", 0)
        assert filter_expr.key == "priority"
        assert filter_expr.value == 0
        assert filter_expr.to_dict() == {"op": "NEQ", "key": "priority", "value": 0}

    def test_neq_with_bool(self):
        """Test NEQ operator with boolean values."""
        filter_expr = NEQ("is_deleted", True)
        assert filter_expr.key == "is_deleted"
        assert filter_expr.value is True
        assert filter_expr.to_dict() == {"op": "NEQ", "key": "is_deleted", "value": True}

    def test_neq_with_none(self):
        """Test NEQ operator with None value."""
        filter_expr = NEQ("error", None)
        assert filter_expr.key == "error"
        assert filter_expr.value is None

    def test_gte_with_int(self):
        """Test GTE operator with integer."""
        filter_expr = GTE("age", 18)
        assert filter_expr.key == "age"
        assert filter_expr.value == 18
        assert filter_expr.to_dict() == {"op": "GTE", "key": "age", "value": 18}

    def test_gte_with_float(self):
        """Test GTE operator with float."""
        filter_expr = GTE("score", 85.5)
        assert filter_expr.key == "score"
        assert filter_expr.value == 85.5
        assert filter_expr.to_dict() == {"op": "GTE", "key": "score", "value": 85.5}

    def test_gte_with_timestamp(self):
        """Test GTE operator with ISO timestamp string."""
        ts = "2025-01-01T00:00:00Z"
        filter_expr = GTE("created_at", ts)
        assert filter_expr.value == ts
        assert filter_expr.to_dict() == {"op": "GTE", "key": "created_at", "value": ts}

    def test_gte_with_zero(self):
        """Test GTE operator with zero (boundary value)."""
        filter_expr = GTE("duration_ms", 0)
        assert filter_expr.value == 0

    def test_lte_with_int(self):
        """Test LTE operator with integer."""
        filter_expr = LTE("age", 65)
        assert filter_expr.key == "age"
        assert filter_expr.value == 65
        assert filter_expr.to_dict() == {"op": "LTE", "key": "age", "value": 65}

    def test_lte_with_float(self):
        """Test LTE operator with float."""
        filter_expr = LTE("price", 99.99)
        assert filter_expr.key == "price"
        assert filter_expr.value == 99.99
        assert filter_expr.to_dict() == {"op": "LTE", "key": "price", "value": 99.99}

    def test_lte_with_timestamp(self):
        """Test LTE operator with ISO timestamp string."""
        ts = "2025-12-31T23:59:59Z"
        filter_expr = LTE("created_at", ts)
        assert filter_expr.value == ts

    def test_lte_with_negative(self):
        """Test LTE operator with negative number."""
        filter_expr = LTE("temperature", -5)
        assert filter_expr.value == -5

    def test_range_with_gte_lte(self):
        """Test range query using GTE and LTE together."""
        filter_expr = AND(GTE("age", 18), LTE("age", 65))
        result = filter_expr.to_dict()
        assert result["op"] == "AND"
        assert result["conditions"][0] == {"op": "GTE", "key": "age", "value": 18}
        assert result["conditions"][1] == {"op": "LTE", "key": "age", "value": 65}

    def test_neq_combined_with_and(self):
        """Test NEQ in complex AND expression."""
        filter_expr = AND(NEQ("status", "archived"), NEQ("status", "deleted"))
        result = filter_expr.to_dict()
        assert len(result["conditions"]) == 2
        assert all(c["op"] == "NEQ" for c in result["conditions"])


class TestStringMatchingOperators:
    """Test string matching operators (CONTAINS, STARTSWITH)."""

    def test_contains_basic(self):
        """Test CONTAINS operator with basic string."""
        filter_expr = CONTAINS("user_id", "admin")
        assert filter_expr.key == "user_id"
        assert filter_expr.value == "admin"
        assert filter_expr.to_dict() == {
            "op": "CONTAINS",
            "key": "user_id",
            "value": "admin",
        }

    def test_contains_with_spaces(self):
        """Test CONTAINS operator with string containing spaces."""
        filter_expr = CONTAINS("name", "John Doe")
        assert filter_expr.value == "John Doe"

    def test_contains_with_empty_string(self):
        """Test CONTAINS operator with empty string."""
        filter_expr = CONTAINS("description", "")
        assert filter_expr.value == ""

    def test_contains_case_sensitivity_note(self):
        """Test CONTAINS stores the value as-is (case handling is in converter)."""
        filter_expr = CONTAINS("name", "ADMIN")
        assert filter_expr.value == "ADMIN"
        result = filter_expr.to_dict()
        assert result["value"] == "ADMIN"

    def test_contains_with_special_characters(self):
        """Test CONTAINS operator with special characters."""
        filter_expr = CONTAINS("path", "/usr/local")
        assert filter_expr.value == "/usr/local"

    def test_startswith_basic(self):
        """Test STARTSWITH operator with basic string."""
        filter_expr = STARTSWITH("name", "Agent")
        assert filter_expr.key == "name"
        assert filter_expr.value == "Agent"
        assert filter_expr.to_dict() == {
            "op": "STARTSWITH",
            "key": "name",
            "value": "Agent",
        }

    def test_startswith_with_prefix(self):
        """Test STARTSWITH operator with common prefix patterns."""
        filter_expr = STARTSWITH("session_id", "sess_")
        assert filter_expr.value == "sess_"

    def test_startswith_with_empty_string(self):
        """Test STARTSWITH operator with empty string."""
        filter_expr = STARTSWITH("name", "")
        assert filter_expr.value == ""

    def test_startswith_with_unicode(self):
        """Test STARTSWITH operator with unicode characters."""
        filter_expr = STARTSWITH("name", "日本")
        assert filter_expr.value == "日本"

    def test_contains_in_and_expression(self):
        """Test CONTAINS within AND expression."""
        filter_expr = AND(
            CONTAINS("user_id", "admin"),
            EQ("status", "OK"),
        )
        result = filter_expr.to_dict()
        assert result["op"] == "AND"
        assert result["conditions"][0]["op"] == "CONTAINS"
        assert result["conditions"][1]["op"] == "EQ"

    def test_startswith_in_or_expression(self):
        """Test STARTSWITH within OR expression."""
        filter_expr = OR(
            STARTSWITH("name", "Agent"),
            STARTSWITH("name", "Team"),
        )
        result = filter_expr.to_dict()
        assert result["op"] == "OR"
        assert all(c["op"] == "STARTSWITH" for c in result["conditions"])

    def test_contains_and_startswith_combined(self):
        """Test combining CONTAINS and STARTSWITH in complex expression."""
        filter_expr = AND(
            CONTAINS("user_id", "user"),
            STARTSWITH("agent_id", "stock_"),
            EQ("status", "OK"),
        )
        result = filter_expr.to_dict()
        assert len(result["conditions"]) == 3

    def test_not_contains(self):
        """Test NOT(CONTAINS(...)) for negated substring match."""
        filter_expr = NOT(CONTAINS("name", "test"))
        result = filter_expr.to_dict()
        assert result["op"] == "NOT"
        assert result["condition"]["op"] == "CONTAINS"
        assert result["condition"]["value"] == "test"


class TestLogicalOperators:
    """Test logical operators (AND, OR, NOT)."""

    def test_and_with_two_conditions(self):
        """Test AND operator with two expressions."""
        filter_expr = AND(EQ("status", "published"), GT("views", 1000))
        assert len(filter_expr.expressions) == 2
        assert filter_expr.to_dict() == {
            "op": "AND",
            "conditions": [
                {"op": "EQ", "key": "status", "value": "published"},
                {"op": "GT", "key": "views", "value": 1000},
            ],
        }

    def test_and_with_multiple_conditions(self):
        """Test AND operator with multiple expressions."""
        filter_expr = AND(
            EQ("status", "active"),
            GT("age", 18),
            LT("age", 65),
            IN("role", ["user", "admin"]),
        )
        assert len(filter_expr.expressions) == 4

    def test_or_with_two_conditions(self):
        """Test OR operator with two expressions."""
        filter_expr = OR(EQ("priority", "high"), EQ("urgent", True))
        assert len(filter_expr.expressions) == 2
        assert filter_expr.to_dict() == {
            "op": "OR",
            "conditions": [
                {"op": "EQ", "key": "priority", "value": "high"},
                {"op": "EQ", "key": "urgent", "value": True},
            ],
        }

    def test_or_with_multiple_conditions(self):
        """Test OR operator with multiple expressions."""
        filter_expr = OR(
            EQ("status", "draft"),
            EQ("status", "published"),
            EQ("status", "archived"),
        )
        assert len(filter_expr.expressions) == 3

    def test_not_with_eq(self):
        """Test NOT operator with EQ expression."""
        filter_expr = NOT(EQ("status", "archived"))
        assert isinstance(filter_expr.expression, EQ)
        assert filter_expr.to_dict() == {
            "op": "NOT",
            "condition": {"op": "EQ", "key": "status", "value": "archived"},
        }

    def test_not_with_in(self):
        """Test NOT operator with IN expression."""
        filter_expr = NOT(IN("user_id", [101, 102, 103]))
        assert filter_expr.to_dict() == {
            "op": "NOT",
            "condition": {"op": "IN", "key": "user_id", "values": [101, 102, 103]},
        }

    def test_not_with_complex_expression(self):
        """Test NOT operator with complex AND expression."""
        filter_expr = NOT(AND(EQ("status", "inactive"), LT("score", 10)))
        assert isinstance(filter_expr.expression, AND)
        assert filter_expr.to_dict() == {
            "op": "NOT",
            "condition": {
                "op": "AND",
                "conditions": [
                    {"op": "EQ", "key": "status", "value": "inactive"},
                    {"op": "LT", "key": "score", "value": 10},
                ],
            },
        }


class TestOperatorOverloading:
    """Test operator overloading (&, |, ~)."""

    def test_and_operator_overload(self):
        """Test & operator creates AND expression."""
        filter_expr = EQ("status", "published") & GT("views", 1000)
        assert isinstance(filter_expr, AND)
        assert len(filter_expr.expressions) == 2

    def test_or_operator_overload(self):
        """Test | operator creates OR expression."""
        filter_expr = EQ("priority", "high") | EQ("urgent", True)
        assert isinstance(filter_expr, OR)
        assert len(filter_expr.expressions) == 2

    def test_not_operator_overload(self):
        """Test ~ operator creates NOT expression."""
        filter_expr = ~EQ("status", "archived")
        assert isinstance(filter_expr, NOT)
        assert isinstance(filter_expr.expression, EQ)

    def test_chained_and_operators(self):
        """Test chaining multiple & operators."""
        filter_expr = EQ("status", "active") & GT("age", 18) & LT("age", 65)
        # Should create nested AND structures
        assert isinstance(filter_expr, AND)

    def test_chained_or_operators(self):
        """Test chaining multiple | operators."""
        filter_expr = EQ("status", "draft") | EQ("status", "published") | EQ("status", "archived")
        # Should create nested OR structures
        assert isinstance(filter_expr, OR)

    def test_mixed_operators(self):
        """Test mixing & and | operators."""
        filter_expr = (EQ("status", "active") & GT("age", 18)) | EQ("role", "admin")
        assert isinstance(filter_expr, OR)

    def test_not_with_and(self):
        """Test ~ operator with AND expression."""
        filter_expr = ~(EQ("status", "inactive") & LT("score", 10))
        assert isinstance(filter_expr, NOT)
        assert isinstance(filter_expr.expression, AND)

    def test_not_with_or(self):
        """Test ~ operator with OR expression."""
        filter_expr = ~(EQ("role", "guest") | EQ("role", "banned"))
        assert isinstance(filter_expr, NOT)
        assert isinstance(filter_expr.expression, OR)


class TestComplexNesting:
    """Test complex nested filter expressions."""

    def test_nested_and_or(self):
        """Test AND within OR."""
        filter_expr = OR(
            AND(EQ("type", "article"), GT("word_count", 500)),
            AND(EQ("type", "tutorial"), LT("difficulty", 5)),
        )
        assert isinstance(filter_expr, OR)
        assert len(filter_expr.expressions) == 2
        assert all(isinstance(e, AND) for e in filter_expr.expressions)

    def test_nested_or_and(self):
        """Test OR within AND."""
        filter_expr = AND(
            EQ("status", "published"),
            OR(EQ("category", "tech"), EQ("category", "science")),
        )
        assert isinstance(filter_expr, AND)
        assert len(filter_expr.expressions) == 2

    def test_deeply_nested_expression(self):
        """Test deeply nested expression with multiple levels."""
        filter_expr = AND(
            EQ("is_active", True),
            OR(
                AND(EQ("tier", "premium"), GT("credits", 100)),
                AND(EQ("tier", "enterprise"), NOT(EQ("suspended", True))),
            ),
        )
        result = filter_expr.to_dict()
        assert result["op"] == "AND"
        assert result["conditions"][1]["op"] == "OR"

    def test_complex_with_not(self):
        """Test complex expression with NOT at different levels."""
        filter_expr = AND(
            NOT(EQ("status", "deleted")),
            OR(GT("score", 80), AND(EQ("tier", "gold"), NOT(LT("age", 18)))),
        )
        assert isinstance(filter_expr, AND)
        assert isinstance(filter_expr.expressions[0], NOT)

    def test_triple_nested_and_or_not(self):
        """Test triple nested AND/OR/NOT combination."""
        filter_expr = OR(
            AND(EQ("region", "US"), NOT(IN("state", ["AK", "HI"]))),
            AND(EQ("region", "EU"), IN("country", ["UK", "FR", "DE"])),
        )
        result = filter_expr.to_dict()
        assert result["op"] == "OR"
        assert len(result["conditions"]) == 2


class TestSerialization:
    """Test to_dict serialization for all operators."""

    def test_eq_serialization(self):
        """Test EQ serialization maintains correct structure."""
        filter_expr = EQ("key", "value")
        result = filter_expr.to_dict()
        assert "op" in result
        assert "key" in result
        assert "value" in result
        assert result["op"] == "EQ"

    def test_in_serialization(self):
        """Test IN serialization maintains list structure."""
        filter_expr = IN("tags", ["python", "javascript"])
        result = filter_expr.to_dict()
        assert result["values"] == ["python", "javascript"]
        assert isinstance(result["values"], list)

    def test_and_serialization_nested(self):
        """Test AND serialization with nested conditions."""
        filter_expr = AND(EQ("a", 1), OR(EQ("b", 2), EQ("c", 3)))
        result = filter_expr.to_dict()
        assert result["conditions"][1]["op"] == "OR"
        assert len(result["conditions"][1]["conditions"]) == 2

    def test_neq_serialization(self):
        """Test NEQ serialization maintains correct structure."""
        filter_expr = NEQ("status", "archived")
        result = filter_expr.to_dict()
        assert result == {"op": "NEQ", "key": "status", "value": "archived"}

    def test_gte_serialization(self):
        """Test GTE serialization maintains correct structure."""
        filter_expr = GTE("age", 18)
        result = filter_expr.to_dict()
        assert result == {"op": "GTE", "key": "age", "value": 18}

    def test_lte_serialization(self):
        """Test LTE serialization maintains correct structure."""
        filter_expr = LTE("price", 100.0)
        result = filter_expr.to_dict()
        assert result == {"op": "LTE", "key": "price", "value": 100.0}

    def test_contains_serialization(self):
        """Test CONTAINS serialization maintains correct structure."""
        filter_expr = CONTAINS("name", "admin")
        result = filter_expr.to_dict()
        assert result == {"op": "CONTAINS", "key": "name", "value": "admin"}

    def test_startswith_serialization(self):
        """Test STARTSWITH serialization maintains correct structure."""
        filter_expr = STARTSWITH("name", "Agent")
        result = filter_expr.to_dict()
        assert result == {"op": "STARTSWITH", "key": "name", "value": "Agent"}

    def test_complex_with_new_operators(self):
        """Test serialization of complex expression with new operators."""
        filter_expr = AND(
            NEQ("status", "archived"),
            GTE("duration_ms", 100),
            LTE("duration_ms", 5000),
            CONTAINS("user_id", "admin"),
            STARTSWITH("name", "Agent"),
        )
        result = filter_expr.to_dict()
        assert result["op"] == "AND"
        assert len(result["conditions"]) == 5
        assert result["conditions"][0]["op"] == "NEQ"
        assert result["conditions"][1]["op"] == "GTE"
        assert result["conditions"][2]["op"] == "LTE"
        assert result["conditions"][3]["op"] == "CONTAINS"
        assert result["conditions"][4]["op"] == "STARTSWITH"

    def test_complex_serialization_roundtrip(self):
        """Test that complex expressions serialize to valid dict structure."""
        filter_expr = OR(
            AND(EQ("status", "published"), GT("views", 1000)),
            NOT(IN("category", ["draft", "archived"])),
        )
        result = filter_expr.to_dict()
        # Verify structure is valid and nested correctly
        assert isinstance(result, dict)
        assert result["op"] == "OR"
        assert isinstance(result["conditions"], list)
        assert result["conditions"][0]["op"] == "AND"
        assert result["conditions"][1]["op"] == "NOT"


class TestDeserialization:
    """Test from_dict deserialization of FilterExpr objects."""

    def test_eq_deserialization(self):
        """Test EQ filter deserialization."""
        original = EQ("status", "published")
        serialized = original.to_dict()

        deserialized = from_dict(serialized)
        assert isinstance(deserialized, EQ)
        assert deserialized.key == "status"
        assert deserialized.value == "published"

    def test_in_deserialization(self):
        """Test IN filter deserialization."""
        original = IN("category", ["tech", "science", "engineering"])
        serialized = original.to_dict()

        deserialized = from_dict(serialized)
        assert isinstance(deserialized, IN)
        assert deserialized.key == "category"
        assert deserialized.values == ["tech", "science", "engineering"]

    def test_gt_deserialization(self):
        """Test GT filter deserialization."""
        original = GT("age", 18)
        serialized = original.to_dict()

        deserialized = from_dict(serialized)
        assert isinstance(deserialized, GT)
        assert deserialized.key == "age"
        assert deserialized.value == 18

    def test_lt_deserialization(self):
        """Test LT filter deserialization."""
        original = LT("price", 100.0)
        serialized = original.to_dict()

        deserialized = from_dict(serialized)
        assert isinstance(deserialized, LT)
        assert deserialized.key == "price"
        assert deserialized.value == 100.0

    def test_neq_deserialization(self):
        """Test NEQ filter deserialization."""
        original = NEQ("status", "archived")
        serialized = original.to_dict()

        deserialized = from_dict(serialized)
        assert isinstance(deserialized, NEQ)
        assert deserialized.key == "status"
        assert deserialized.value == "archived"

    def test_gte_deserialization(self):
        """Test GTE filter deserialization."""
        original = GTE("age", 18)
        serialized = original.to_dict()

        deserialized = from_dict(serialized)
        assert isinstance(deserialized, GTE)
        assert deserialized.key == "age"
        assert deserialized.value == 18

    def test_lte_deserialization(self):
        """Test LTE filter deserialization."""
        original = LTE("price", 99.99)
        serialized = original.to_dict()

        deserialized = from_dict(serialized)
        assert isinstance(deserialized, LTE)
        assert deserialized.key == "price"
        assert deserialized.value == 99.99

    def test_contains_deserialization(self):
        """Test CONTAINS filter deserialization."""
        original = CONTAINS("user_id", "admin")
        serialized = original.to_dict()

        deserialized = from_dict(serialized)
        assert isinstance(deserialized, CONTAINS)
        assert deserialized.key == "user_id"
        assert deserialized.value == "admin"

    def test_startswith_deserialization(self):
        """Test STARTSWITH filter deserialization."""
        original = STARTSWITH("name", "Agent")
        serialized = original.to_dict()

        deserialized = from_dict(serialized)
        assert isinstance(deserialized, STARTSWITH)
        assert deserialized.key == "name"
        assert deserialized.value == "Agent"

    def test_invalid_neq_missing_fields(self):
        """Test NEQ deserialization with missing fields raises ValueError."""
        with pytest.raises(ValueError, match="NEQ filter requires"):
            from_dict({"op": "NEQ", "key": "status"})

    def test_invalid_gte_missing_fields(self):
        """Test GTE deserialization with missing fields raises ValueError."""
        with pytest.raises(ValueError, match="GTE filter requires"):
            from_dict({"op": "GTE", "key": "age"})

    def test_invalid_lte_missing_fields(self):
        """Test LTE deserialization with missing fields raises ValueError."""
        with pytest.raises(ValueError, match="LTE filter requires"):
            from_dict({"op": "LTE", "value": 100})

    def test_invalid_contains_missing_fields(self):
        """Test CONTAINS deserialization with missing fields raises ValueError."""
        with pytest.raises(ValueError, match="CONTAINS filter requires"):
            from_dict({"op": "CONTAINS", "key": "name"})

    def test_invalid_startswith_missing_fields(self):
        """Test STARTSWITH deserialization with missing fields raises ValueError."""
        with pytest.raises(ValueError, match="STARTSWITH filter requires"):
            from_dict({"op": "STARTSWITH", "value": "Agent"})

    def test_and_deserialization(self):
        """Test AND filter deserialization."""
        original = AND(EQ("status", "published"), GT("views", 1000))
        serialized = original.to_dict()

        deserialized = from_dict(serialized)
        assert isinstance(deserialized, AND)
        assert len(deserialized.expressions) == 2
        assert isinstance(deserialized.expressions[0], EQ)
        assert isinstance(deserialized.expressions[1], GT)

    def test_or_deserialization(self):
        """Test OR filter deserialization."""
        original = OR(EQ("priority", "high"), EQ("urgent", True))
        serialized = original.to_dict()

        deserialized = from_dict(serialized)
        assert isinstance(deserialized, OR)
        assert len(deserialized.expressions) == 2

    def test_not_deserialization(self):
        """Test NOT filter deserialization."""
        original = NOT(EQ("status", "archived"))
        serialized = original.to_dict()

        deserialized = from_dict(serialized)
        assert isinstance(deserialized, NOT)
        assert isinstance(deserialized.expression, EQ)

    def test_complex_nested_deserialization(self):
        """Test complex nested filter deserialization."""
        original = (EQ("type", "article") & GT("word_count", 500)) | (
            EQ("type", "tutorial") & ~EQ("difficulty", "beginner")
        )
        serialized = original.to_dict()

        deserialized = from_dict(serialized)
        assert isinstance(deserialized, OR)
        assert len(deserialized.expressions) == 2
        assert isinstance(deserialized.expressions[0], AND)
        assert isinstance(deserialized.expressions[1], AND)

    def test_operator_overload_deserialization(self):
        """Test deserialization of filters created with operator overloads."""
        # Using & operator
        filter1 = EQ("status", "published") & GT("views", 1000)
        deserialized1 = from_dict(filter1.to_dict())
        assert isinstance(deserialized1, AND)

        # Using | operator
        filter2 = EQ("priority", "high") | EQ("urgent", True)
        deserialized2 = from_dict(filter2.to_dict())
        assert isinstance(deserialized2, OR)

        # Using ~ operator
        filter3 = ~EQ("status", "draft")
        deserialized3 = from_dict(filter3.to_dict())
        assert isinstance(deserialized3, NOT)

    def test_invalid_dict_missing_op(self):
        """Test from_dict with missing 'op' key raises ValueError."""
        with pytest.raises(ValueError, match="must contain 'op' key"):
            from_dict({"key": "status", "value": "published"})

    def test_invalid_dict_unknown_op(self):
        """Test from_dict with unknown operator raises ValueError."""
        with pytest.raises(ValueError, match="Unknown filter operator"):
            from_dict({"op": "UNKNOWN", "key": "status", "value": "published"})

    def test_invalid_eq_missing_fields(self):
        """Test EQ deserialization with missing fields raises ValueError."""
        with pytest.raises(ValueError, match="EQ filter requires"):
            from_dict({"op": "EQ", "key": "status"})

    def test_invalid_in_missing_fields(self):
        """Test IN deserialization with missing fields raises ValueError."""
        with pytest.raises(ValueError, match="IN filter requires"):
            from_dict({"op": "IN", "key": "category"})

    def test_invalid_and_missing_conditions(self):
        """Test AND deserialization with missing conditions raises ValueError."""
        with pytest.raises(ValueError, match="AND filter requires 'conditions' field"):
            from_dict({"op": "AND"})

    def test_invalid_or_missing_conditions(self):
        """Test OR deserialization with missing conditions raises ValueError."""
        with pytest.raises(ValueError, match="OR filter requires 'conditions' field"):
            from_dict({"op": "OR"})

    def test_invalid_not_missing_condition(self):
        """Test NOT deserialization with missing condition raises ValueError."""
        with pytest.raises(ValueError, match="NOT filter requires 'condition' field"):
            from_dict({"op": "NOT"})

    def test_complex_nested_with_new_operators(self):
        """Test complex nested deserialization with new operators."""
        original = AND(
            NEQ("status", "archived"),
            OR(
                CONTAINS("user_id", "admin"),
                STARTSWITH("agent_id", "stock_"),
            ),
            GTE("duration_ms", 100),
            LTE("duration_ms", 5000),
        )
        serialized = original.to_dict()

        deserialized = from_dict(serialized)
        assert isinstance(deserialized, AND)
        assert len(deserialized.expressions) == 4
        assert isinstance(deserialized.expressions[0], NEQ)
        assert isinstance(deserialized.expressions[1], OR)
        assert isinstance(deserialized.expressions[2], GTE)
        assert isinstance(deserialized.expressions[3], LTE)

        # Verify nested OR
        or_expr = deserialized.expressions[1]
        assert isinstance(or_expr.expressions[0], CONTAINS)
        assert isinstance(or_expr.expressions[1], STARTSWITH)

    def test_roundtrip_preserves_semantics(self):
        """Test that serialization -> deserialization preserves filter semantics."""
        filters = [
            EQ("status", "published"),
            IN("category", ["tech", "science"]),
            GT("views", 1000),
            LT("age", 65),
            NEQ("status", "archived"),
            GTE("age", 18),
            LTE("price", 100.0),
            CONTAINS("name", "admin"),
            STARTSWITH("session_id", "sess_"),
            EQ("active", True) & GT("score", 80),
            EQ("priority", "high") | EQ("urgent", True),
            ~EQ("status", "archived"),
            (EQ("type", "article") & GT("word_count", 500)) | (EQ("type", "tutorial")),
            AND(NEQ("status", "deleted"), GTE("duration_ms", 0), CONTAINS("user_id", "test")),
        ]

        for original in filters:
            serialized = original.to_dict()
            deserialized = from_dict(serialized)

            # Re-serialize to compare structure
            reserialized = deserialized.to_dict()
            assert serialized == reserialized, f"Roundtrip failed for {original}"


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_special_characters_in_strings(self):
        """Test filters with special characters."""
        filter_expr = EQ("name", "O'Brien")
        assert filter_expr.value == "O'Brien"

        filter_expr = EQ("path", "/usr/local/bin")
        assert filter_expr.value == "/usr/local/bin"

    def test_unicode_characters(self):
        """Test filters with unicode characters."""
        filter_expr = EQ("name", "François")
        assert filter_expr.value == "François"

        filter_expr = IN("languages", ["中文", "日本語", "한국어"])
        assert "中文" in filter_expr.values

    def test_very_large_numbers(self):
        """Test filters with very large numbers."""
        filter_expr = GT("timestamp", 1234567890123456)
        assert filter_expr.value == 1234567890123456

    def test_floating_point_precision(self):
        """Test filters with floating point numbers."""
        filter_expr = EQ("price", 19.99999)
        assert filter_expr.value == 19.99999

    def test_empty_string(self):
        """Test EQ with empty string."""
        filter_expr = EQ("description", "")
        assert filter_expr.value == ""

    def test_whitespace_string(self):
        """Test EQ with whitespace string."""
        filter_expr = EQ("name", "   ")
        assert filter_expr.value == "   "

    def test_in_with_mixed_types(self):
        """Test IN operator with mixed types in list."""
        filter_expr = IN("value", [1, "two", 3.0, True])
        assert filter_expr.values == [1, "two", 3.0, True]

    def test_multiple_ands_same_key(self):
        """Test multiple AND conditions on same key (range query)."""
        filter_expr = AND(GT("age", 18), LT("age", 65))
        result = filter_expr.to_dict()
        assert len(result["conditions"]) == 2


class TestRepr:
    """Test string representation of filter expressions."""

    def test_eq_repr(self):
        """Test EQ __repr__ output."""
        filter_expr = EQ("status", "published")
        repr_str = repr(filter_expr)
        assert "EQ" in repr_str
        assert "status" in repr_str

    def test_and_repr(self):
        """Test AND __repr__ output."""
        filter_expr = AND(EQ("a", 1), EQ("b", 2))
        repr_str = repr(filter_expr)
        assert "AND" in repr_str

    def test_neq_repr(self):
        """Test NEQ __repr__ output."""
        filter_expr = NEQ("status", "archived")
        repr_str = repr(filter_expr)
        assert "NEQ" in repr_str
        assert "status" in repr_str

    def test_gte_repr(self):
        """Test GTE __repr__ output."""
        filter_expr = GTE("age", 18)
        repr_str = repr(filter_expr)
        assert "GTE" in repr_str

    def test_lte_repr(self):
        """Test LTE __repr__ output."""
        filter_expr = LTE("price", 99.99)
        repr_str = repr(filter_expr)
        assert "LTE" in repr_str

    def test_contains_repr(self):
        """Test CONTAINS __repr__ output."""
        filter_expr = CONTAINS("name", "admin")
        repr_str = repr(filter_expr)
        assert "CONTAINS" in repr_str

    def test_startswith_repr(self):
        """Test STARTSWITH __repr__ output."""
        filter_expr = STARTSWITH("name", "Agent")
        repr_str = repr(filter_expr)
        assert "STARTSWITH" in repr_str

    def test_complex_repr(self):
        """Test complex expression __repr__ is valid."""
        filter_expr = OR(AND(EQ("a", 1), GT("b", 2)), NOT(EQ("c", 3)))
        repr_str = repr(filter_expr)
        assert isinstance(repr_str, str)
        assert len(repr_str) > 0


class TestRealWorldScenarios:
    """Test real-world usage scenarios from the cookbook examples."""

    def test_sales_data_filtering(self):
        """Test filtering sales data by region (from cookbook example)."""
        filter_expr = IN("region", ["north_america"])
        assert filter_expr.to_dict() == {
            "op": "IN",
            "key": "region",
            "values": ["north_america"],
        }

    def test_exclude_region(self):
        """Test excluding a region with NOT."""
        filter_expr = NOT(IN("region", ["north_america"]))
        result = filter_expr.to_dict()
        assert result["op"] == "NOT"
        assert result["condition"]["op"] == "IN"

    def test_sales_and_not_region(self):
        """Test combining data_type check with region exclusion."""
        filter_expr = AND(EQ("data_type", "sales"), NOT(EQ("region", "north_america")))
        result = filter_expr.to_dict()
        assert result["op"] == "AND"
        assert result["conditions"][0]["value"] == "sales"
        assert result["conditions"][1]["op"] == "NOT"

    def test_cv_filtering_by_users(self):
        """Test filtering CVs by user_id (from team cookbook example)."""
        filter_expr = IN(
            "user_id",
            [
                "jordan_mitchell",
                "taylor_brooks",
                "morgan_lee",
                "casey_jordan",
                "alex_rivera",
            ],
        )
        assert len(filter_expr.values) == 5

    def test_cv_complex_filter(self):
        """Test complex CV filtering with AND/NOT combination."""
        filter_expr = AND(
            IN("user_id", ["jordan_mitchell", "taylor_brooks"]),
            NOT(IN("user_id", ["morgan_lee", "casey_jordan", "alex_rivera"])),
        )
        result = filter_expr.to_dict()
        assert result["op"] == "AND"
        assert result["conditions"][1]["op"] == "NOT"

    def test_or_with_nonexistent_fallback(self):
        """Test OR with non-existent value fallback."""
        filter_expr = OR(EQ("user_id", "this candidate does not exist"), EQ("year", 2020))
        result = filter_expr.to_dict()
        assert result["op"] == "OR"
        assert len(result["conditions"]) == 2

    def test_multiple_metadata_fields(self):
        """Test filtering on multiple metadata fields."""
        filter_expr = AND(
            EQ("data_type", "sales"),
            EQ("year", 2024),
            IN("currency", ["USD", "EUR"]),
            NOT(EQ("archived", True)),
        )
        assert len(filter_expr.expressions) == 4


class TestTypeValidation:
    """Test that operators work with expected types."""

    def test_eq_accepts_any_type(self):
        """Test that EQ works with various Python types."""
        # These should all work without errors
        EQ("str_field", "value")
        EQ("int_field", 42)
        EQ("float_field", 3.14)
        EQ("bool_field", True)
        EQ("none_field", None)
        EQ("list_field", [1, 2, 3])
        EQ("dict_field", {"key": "value"})

    def test_in_requires_list(self):
        """Test IN operator with list values."""
        # Should work with lists
        filter_expr = IN("field", [1, 2, 3])
        assert isinstance(filter_expr.values, list)

    def test_comparison_operators_with_strings(self):
        """Test GT/LT can be used with strings (lexicographic comparison)."""
        # These should work (implementation dependent on vector DB)
        GT("name", "A")
        LT("name", "Z")

    def test_and_or_require_filter_expressions(self):
        """Test that AND/OR work with FilterExpr instances."""
        # Should work with proper FilterExpr objects
        and_expr = AND(EQ("a", 1), EQ("b", 2))
        assert all(isinstance(e, FilterExpr) for e in and_expr.expressions)

        or_expr = OR(EQ("a", 1), EQ("b", 2))
        assert all(isinstance(e, FilterExpr) for e in or_expr.expressions)


class TestUsagePatterns:
    """Test proper usage patterns and common mistakes."""

    def test_single_filter_should_be_wrapped_in_list(self):
        """Test that single filters work when properly wrapped."""
        # Correct usage: wrap single filter in list
        filters = [EQ("status", "active")]
        assert isinstance(filters, list)
        assert len(filters) == 1
        assert isinstance(filters[0], FilterExpr)

    def test_multiple_filters_in_list(self):
        """Test multiple independent filters in a list."""
        # When passing multiple filters, they should all be in a list
        filters = [
            EQ("status", "active"),
            GT("age", 18),
            IN("category", ["tech", "science"]),
        ]
        assert isinstance(filters, list)
        assert len(filters) == 3
        assert all(isinstance(f, FilterExpr) for f in filters)

    def test_list_with_single_complex_expression(self):
        """Test list containing single complex AND/OR expression."""
        # Single complex expression wrapped in list
        filters = [AND(EQ("status", "active"), GT("score", 80))]
        assert isinstance(filters, list)
        assert len(filters) == 1
        assert isinstance(filters[0], AND)

    def test_list_with_multiple_complex_expressions(self):
        """Test list with multiple complex expressions."""
        # Multiple complex expressions in list
        filters = [
            AND(EQ("type", "article"), GT("views", 1000)),
            OR(EQ("featured", True), GT("score", 90)),
        ]
        assert isinstance(filters, list)
        assert len(filters) == 2

    def test_filter_expr_is_not_iterable(self):
        """Test that FilterExpr objects are not directly iterable."""
        # This test documents that you cannot iterate over a single filter
        # You must wrap it in a list first
        filter_expr = EQ("status", "active")

        # Attempting to iterate over a FilterExpr will fail
        try:
            list(filter_expr)  # This should fail
            assert False, "Expected TypeError when iterating over FilterExpr"
        except TypeError:
            pass  # Expected behavior

    def test_correct_way_to_pass_single_filter(self):
        """Test the correct way to pass a single filter to a list-expecting function."""

        # Simulate what knowledge_filters parameter expects
        def validate_filters(filters):
            """Simulate filter validation that expects a list."""
            if isinstance(filters, list):
                for f in filters:
                    if not isinstance(f, FilterExpr):
                        raise ValueError(f"Expected FilterExpr, got {type(f)}")
                return True
            else:
                raise TypeError("filters must be a list")

        # Correct: single filter wrapped in list
        correct_usage = [EQ("user_id", "123")]
        assert validate_filters(correct_usage)

        # Incorrect: single filter without list (would fail)
        incorrect_usage = EQ("user_id", "123")
        try:
            validate_filters(incorrect_usage)
            assert False, "Should have raised TypeError"
        except TypeError:
            pass  # Expected

    def test_empty_filter_list(self):
        """Test that empty filter list is valid."""
        filters = []
        assert isinstance(filters, list)
        assert len(filters) == 0


class TestTraceFilterScenarios:
    """Test real-world trace filtering scenarios matching the FE advanced filter bar."""

    def test_status_equals_ok(self):
        """Test filtering traces where status = OK."""
        filter_expr = EQ("status", "OK")
        result = filter_expr.to_dict()
        assert result == {"op": "EQ", "key": "status", "value": "OK"}

    def test_status_not_error(self):
        """Test filtering traces where status != ERROR."""
        filter_expr = NEQ("status", "ERROR")
        result = filter_expr.to_dict()
        assert result == {"op": "NEQ", "key": "status", "value": "ERROR"}

    def test_user_id_contains(self):
        """Test filtering traces where user_id contains 'admin'."""
        filter_expr = CONTAINS("user_id", "admin")
        result = filter_expr.to_dict()
        assert result == {"op": "CONTAINS", "key": "user_id", "value": "admin"}

    def test_status_ok_and_user_contains(self):
        """Test composite: status = OK AND user_id contains 'user'."""
        filter_expr = AND(
            EQ("status", "OK"),
            CONTAINS("user_id", "user"),
        )
        result = filter_expr.to_dict()
        assert result["op"] == "AND"
        assert len(result["conditions"]) == 2
        assert result["conditions"][0] == {"op": "EQ", "key": "status", "value": "OK"}
        assert result["conditions"][1] == {"op": "CONTAINS", "key": "user_id", "value": "user"}

    def test_duration_range_filter(self):
        """Test filtering traces by duration range (100ms to 5000ms)."""
        filter_expr = AND(
            GTE("duration_ms", 100),
            LTE("duration_ms", 5000),
        )
        result = filter_expr.to_dict()
        assert result["conditions"][0] == {"op": "GTE", "key": "duration_ms", "value": 100}
        assert result["conditions"][1] == {"op": "LTE", "key": "duration_ms", "value": 5000}

    def test_agent_id_startswith(self):
        """Test filtering traces where agent_id starts with 'stock_'."""
        filter_expr = STARTSWITH("agent_id", "stock_")
        result = filter_expr.to_dict()
        assert result == {"op": "STARTSWITH", "key": "agent_id", "value": "stock_"}

    def test_multiple_agent_ids(self):
        """Test filtering traces for multiple agent IDs."""
        filter_expr = IN("agent_id", ["stock_agent", "weather_agent", "news_agent"])
        result = filter_expr.to_dict()
        assert result["op"] == "IN"
        assert len(result["values"]) == 3

    def test_complex_trace_search(self):
        """Test complex trace search: (status=OK AND agent_id starts with 'stock') OR (status=ERROR AND duration > 5000)."""
        filter_expr = OR(
            AND(EQ("status", "OK"), STARTSWITH("agent_id", "stock")),
            AND(EQ("status", "ERROR"), GT("duration_ms", 5000)),
        )
        result = filter_expr.to_dict()
        assert result["op"] == "OR"
        assert len(result["conditions"]) == 2
        assert result["conditions"][0]["op"] == "AND"
        assert result["conditions"][1]["op"] == "AND"

    def test_time_range_filter(self):
        """Test filtering traces by time range."""
        filter_expr = AND(
            GTE("start_time", "2025-01-01T00:00:00Z"),
            LTE("end_time", "2025-12-31T23:59:59Z"),
        )
        result = filter_expr.to_dict()
        assert result["op"] == "AND"
        assert result["conditions"][0]["op"] == "GTE"
        assert result["conditions"][1]["op"] == "LTE"

    def test_exclude_specific_sessions(self):
        """Test filtering traces excluding specific sessions."""
        filter_expr = AND(
            EQ("status", "OK"),
            NOT(IN("session_id", ["test-session-1", "test-session-2"])),
        )
        result = filter_expr.to_dict()
        assert result["op"] == "AND"
        assert result["conditions"][1]["op"] == "NOT"
        assert result["conditions"][1]["condition"]["op"] == "IN"

    def test_workflow_traces_with_duration(self):
        """Test filtering workflow traces with minimum duration."""
        filter_expr = AND(
            NEQ("workflow_id", None),
            GTE("duration_ms", 1000),
        )
        result = filter_expr.to_dict()
        assert result["op"] == "AND"
        assert result["conditions"][0]["op"] == "NEQ"

    def test_search_request_body_structure(self):
        """Test the structure of a search request body as sent by the FE."""
        filter_dict = AND(
            EQ("status", "OK"),
            CONTAINS("user_id", "admin"),
        ).to_dict()

        request_body = {
            "filter": filter_dict,
            "page": 1,
            "limit": 20,
        }

        assert "filter" in request_body
        assert request_body["filter"]["op"] == "AND"
        assert request_body["page"] == 1
        assert request_body["limit"] == 20

    def test_all_trace_filter_operators_roundtrip(self):
        """Test roundtrip for all operators applicable to trace filtering."""
        trace_filters = [
            EQ("status", "OK"),
            NEQ("status", "ERROR"),
            GT("duration_ms", 100),
            GTE("duration_ms", 100),
            LT("duration_ms", 5000),
            LTE("duration_ms", 5000),
            IN("status", ["OK", "ERROR"]),
            CONTAINS("user_id", "admin"),
            STARTSWITH("name", "Agent"),
            AND(EQ("status", "OK"), GT("duration_ms", 0)),
            OR(EQ("agent_id", "a1"), EQ("agent_id", "a2")),
            NOT(EQ("status", "ERROR")),
        ]

        for original in trace_filters:
            serialized = original.to_dict()
            deserialized = from_dict(serialized)
            reserialized = deserialized.to_dict()
            assert serialized == reserialized, f"Roundtrip failed for {original}"
