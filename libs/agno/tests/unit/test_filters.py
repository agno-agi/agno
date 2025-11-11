"""Unit tests for search filter expressions.

Tests cover:
- Basic filter operators (EQ, IN, GT, LT)
- Logical operators (AND, OR, NOT)
- Operator overloading (&, |, ~)
- Serialization (to_dict)
- Deserialization (from_dict)
- Complex nested expressions
- Edge cases
"""

import pytest

from agno.filters import AND, EQ, GT, IN, LT, NOT, OR, FilterExpr, from_dict


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

    def test_roundtrip_preserves_semantics(self):
        """Test that serialization -> deserialization preserves filter semantics."""
        filters = [
            EQ("status", "published"),
            IN("category", ["tech", "science"]),
            GT("views", 1000),
            LT("age", 65),
            EQ("active", True) & GT("score", 80),
            EQ("priority", "high") | EQ("urgent", True),
            ~EQ("status", "archived"),
            (EQ("type", "article") & GT("word_count", 500)) | (EQ("type", "tutorial")),
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
