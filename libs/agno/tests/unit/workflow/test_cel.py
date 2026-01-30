"""Unit tests for CEL (Common Expression Language) support in workflows."""

import pytest

from agno.workflow.cel import (
    CEL_AVAILABLE,
    is_cel_expression,
    validate_cel_expression,
)


class TestIsCelExpression:
    """Tests for is_cel_expression function."""

    # ============================================================================
    # SIMPLE IDENTIFIERS (Should return False - these are function names)
    # ============================================================================

    def test_simple_identifier(self):
        """Simple function names should return False."""
        assert is_cel_expression("my_evaluator") is False

    def test_simple_identifier_with_numbers(self):
        """Function names with numbers should return False."""
        assert is_cel_expression("evaluator_v2") is False
        assert is_cel_expression("step1") is False

    def test_simple_identifier_camelcase(self):
        """CamelCase function names should return False."""
        assert is_cel_expression("myEvaluator") is False
        assert is_cel_expression("checkCondition") is False

    def test_simple_identifier_underscore_prefix(self):
        """Private function names with underscore prefix should return False."""
        assert is_cel_expression("_private_func") is False
        assert is_cel_expression("__double_underscore") is False

    def test_simple_identifier_single_char(self):
        """Single character identifiers should return False."""
        assert is_cel_expression("x") is False
        assert is_cel_expression("_") is False

    # ============================================================================
    # DOT OPERATOR (Should return True - method calls, property access)
    # ============================================================================

    def test_dot_method_call(self):
        """Method calls with dot should return True."""
        assert is_cel_expression("input.contains('test')") is True
        assert is_cel_expression("input.size()") is True
        assert is_cel_expression("previous_step_content.startsWith('hello')") is True

    def test_dot_property_access(self):
        """Property access with dot should return True."""
        assert is_cel_expression("additional_data.route") is True
        assert is_cel_expression("session_state.user_type") is True

    def test_dot_chained_access(self):
        """Chained property/method access should return True."""
        assert is_cel_expression("additional_data.user.name") is True
        assert is_cel_expression("input.trim().size()") is True

    # ============================================================================
    # COMPARISON OPERATORS (Should return True)
    # ============================================================================

    def test_equality_operators(self):
        """Equality operators should return True."""
        assert is_cel_expression("x == 5") is True
        assert is_cel_expression("name != 'admin'") is True
        assert is_cel_expression("previous_step_name == 'step1'") is True

    def test_comparison_operators(self):
        """Comparison operators should return True."""
        assert is_cel_expression("size > 100") is True
        assert is_cel_expression("count < 10") is True
        assert is_cel_expression("age >= 18") is True
        assert is_cel_expression("score <= 100") is True

    # ============================================================================
    # LOGICAL OPERATORS (Should return True)
    # ============================================================================

    def test_and_operator(self):
        """AND operator should return True."""
        assert is_cel_expression("a && b") is True
        assert is_cel_expression("previous_step_content.size() > 0 && input.size() > 0") is True

    def test_or_operator(self):
        """OR operator should return True."""
        assert is_cel_expression("a || b") is True
        assert is_cel_expression("is_admin || is_moderator") is True

    def test_not_operator(self):
        """NOT operator should return True."""
        assert is_cel_expression("!is_empty") is True
        assert is_cel_expression("!all_success") is True

    def test_complex_logical(self):
        """Complex logical expressions should return True."""
        assert is_cel_expression("(a && b) || (c && d)") is True
        assert is_cel_expression("!empty && size > 0") is True

    # ============================================================================
    # ARITHMETIC OPERATORS (Should return True)
    # ============================================================================

    def test_arithmetic_operators(self):
        """Arithmetic operators should return True."""
        assert is_cel_expression("a + b") is True
        assert is_cel_expression("x - y") is True
        assert is_cel_expression("count * 2") is True
        assert is_cel_expression("total / 4") is True
        assert is_cel_expression("num % 2") is True

    # ============================================================================
    # TERNARY OPERATOR (Should return True)
    # ============================================================================

    def test_ternary_operator(self):
        """Ternary operator should return True."""
        assert is_cel_expression("condition ? 'yes' : 'no'") is True
        assert is_cel_expression("x > 0 ? x : -x") is True
        assert is_cel_expression('input.contains("video") ? "video_step" : "image_step"') is True

    # ============================================================================
    # PARENTHESES AND BRACKETS (Should return True)
    # ============================================================================

    def test_parentheses(self):
        """Parentheses should return True."""
        assert is_cel_expression("(a)") is True
        assert is_cel_expression("func()") is True
        assert is_cel_expression("(x + y) * z") is True

    def test_brackets(self):
        """Brackets (array/map access) should return True."""
        assert is_cel_expression("arr[0]") is True
        assert is_cel_expression("map['key']") is True
        assert is_cel_expression("additional_data['route']") is True

    # ============================================================================
    # STRING LITERALS (Should return True)
    # ============================================================================

    def test_double_quoted_strings(self):
        """Double-quoted strings should return True."""
        assert is_cel_expression('"hello"') is True
        assert is_cel_expression('input == "test"') is True

    def test_single_quoted_strings(self):
        """Single-quoted strings should return True."""
        assert is_cel_expression("'hello'") is True
        assert is_cel_expression("input == 'test'") is True

    # ============================================================================
    # BOOLEAN LITERALS
    # ============================================================================

    def test_true_literal_standalone(self):
        """Standalone 'true' matches identifier regex, so returns False.

        This is correct behavior - the function can't distinguish between
        a function named 'true' and the CEL boolean literal. Users should
        use selector_type='cel' explicitly if needed.
        """
        assert is_cel_expression("true") is False

    def test_true_literal_in_expression(self):
        """'true' in an expression context should return True."""
        assert is_cel_expression("has_content == true") is True

    def test_false_literal_standalone(self):
        """Standalone 'false' matches identifier regex, so returns False."""
        assert is_cel_expression("false") is False

    def test_false_literal_in_expression(self):
        """'false' in an expression context should return True."""
        assert is_cel_expression("is_empty == false") is True

    # ============================================================================
    # IN OPERATOR (Should return True)
    # ============================================================================

    def test_in_operator(self):
        """'in' operator should return True."""
        assert is_cel_expression("x in list") is True
        assert is_cel_expression("'admin' in roles") is True
        assert is_cel_expression("name in allowed_names") is True

    # ============================================================================
    # REAL-WORLD CEL EXPRESSIONS FROM COOKBOOKS
    # ============================================================================

    def test_cookbook_condition_examples(self):
        """Test CEL expressions from condition cookbooks."""
        # Basic condition
        assert is_cel_expression('input.contains("urgent")') is True
        # Previous step content check
        assert is_cel_expression("previous_step_content.size() > 500") is True
        # Additional data access
        assert is_cel_expression('additional_data.priority == "high"') is True
        # Session state
        assert is_cel_expression("session_state.request_count > 5") is True
        # Combined conditions
        assert is_cel_expression('previous_step_content.size() > 0 && previous_step_content.contains("error")') is True

    def test_cookbook_loop_examples(self):
        """Test CEL expressions from loop cookbooks."""
        # Iteration check
        assert is_cel_expression("current_iteration >= 3") is True
        # Max iterations
        assert is_cel_expression("current_iteration >= max_iterations - 1") is True
        # Success check - standalone identifier returns False (matches identifier regex)
        # In practice, this is used in compound expressions like "all_success && current_iteration >= 2"
        assert is_cel_expression("all_success") is False
        assert is_cel_expression("all_success && current_iteration >= 2") is True
        # Last step content
        assert is_cel_expression('last_step_content.contains("DONE")') is True
        # Step outputs map
        assert is_cel_expression("step_outputs.size() >= 2") is True
        assert is_cel_expression('step_outputs.Research.contains("DONE")') is True

    def test_cookbook_router_examples(self):
        """Test CEL expressions from router cookbooks."""
        # Route based on input
        assert is_cel_expression('input.contains("video") ? "video_step" : "image_step"') is True
        # Additional data routing
        assert is_cel_expression("additional_data.route") is True
        # Compound selector
        assert is_cel_expression('additional_data.priority == "high" ? "fast_step" : "normal_step"') is True

    # ============================================================================
    # EDGE CASES
    # ============================================================================

    def test_empty_string(self):
        """Empty string should return False (not a valid expression or function)."""
        assert is_cel_expression("") is False

    def test_whitespace_only(self):
        """Whitespace-only string should return False."""
        assert is_cel_expression("   ") is False

    def test_numbers_only(self):
        """Numbers are not valid identifiers, but also not CEL expressions."""
        # Numbers starting with digit don't match identifier regex
        # But they also don't contain CEL indicators
        assert is_cel_expression("123") is False
        assert is_cel_expression("3point14") is False

    def test_dotted_module_path_like(self):
        """Dotted strings that look like module paths should return True.

        Note: This is a tradeoff - 'my.evaluator' looks like a module path but
        will be detected as CEL due to the dot. This is acceptable because:
        1. Registry lookups use simple function names, not dotted paths
        2. If someone needs a dotted name, they can use selector_type='function'
        """
        assert is_cel_expression("my.evaluator") is True
        assert is_cel_expression("module.submodule.func") is True

    def test_reserved_words_standalone(self):
        """Standalone reserved words match identifier regex, so return False.

        This is a known limitation - 'true', 'false', 'all_success' etc.
        are valid Python identifiers. The function prioritizes avoiding
        false positives (treating function names as CEL) over catching
        these edge cases. Users can use selector_type='cel' explicitly.
        """
        assert is_cel_expression("true") is False
        assert is_cel_expression("false") is False
        # But when used in expressions, they're detected
        assert is_cel_expression("x == true") is True
        assert is_cel_expression("y == false") is True

    def test_reserved_words_in_identifier(self):
        """Identifiers containing reserved words should return False if valid identifier."""
        # 'true' and 'false' as substrings in valid identifiers
        assert is_cel_expression("is_true") is False
        assert is_cel_expression("check_false") is False
        assert is_cel_expression("trueValue") is False
        assert is_cel_expression("falseFlag") is False


class TestValidateCelExpression:
    """Tests for validate_cel_expression function."""

    @pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
    def test_valid_simple_expression(self):
        """Valid simple expressions should validate."""
        assert validate_cel_expression("true") is True
        assert validate_cel_expression("false") is True
        assert validate_cel_expression("1 + 2") is True

    @pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
    def test_valid_comparison(self):
        """Valid comparison expressions should validate."""
        assert validate_cel_expression("x > 5") is True
        assert validate_cel_expression("name == 'test'") is True

    @pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
    def test_valid_logical(self):
        """Valid logical expressions should validate."""
        assert validate_cel_expression("a && b") is True
        assert validate_cel_expression("a || b") is True
        assert validate_cel_expression("!flag") is True

    @pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
    def test_valid_ternary(self):
        """Valid ternary expressions should validate."""
        assert validate_cel_expression("x ? 'yes' : 'no'") is True

    @pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
    def test_valid_method_call(self):
        """Valid method call expressions should validate."""
        assert validate_cel_expression("'hello'.size()") is True
        assert validate_cel_expression("'test'.contains('es')") is True

    @pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
    def test_invalid_syntax(self):
        """Invalid syntax should not validate."""
        assert validate_cel_expression("x +") is False
        assert validate_cel_expression("((())") is False
        assert validate_cel_expression("a && ") is False

    @pytest.mark.skipif(not CEL_AVAILABLE, reason="cel-python not installed")
    def test_empty_expression(self):
        """Empty expression should not validate."""
        assert validate_cel_expression("") is False
