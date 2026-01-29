"""Validate CEL expressions before using them.

Demonstrates using validate_cel_expression() to check syntax
before saving workflow configurations -- useful for UI validation.

Requirements:
    pip install cel-python
"""

from agno.workflow import CEL_AVAILABLE, validate_cel_expression

if not CEL_AVAILABLE:
    print("CEL is not available. Install with: pip install cel-python")
    exit(1)

expressions = [
    # Valid expressions
    ('input.contains("urgent")', True),
    ("session_state.count > 5", True),
    ("additional_data.priority >= 1 && additional_data.priority <= 10", True),
    ('has_previous_step_content && previous_step_content.contains("error")', True),
    ("size(previous_step_contents) > 0", True),
    # Invalid expressions
    ("input.contains(", False),
    (">>> not valid <<<", False),
]

if __name__ == "__main__":
    print("CEL Expression Validation")
    print("=" * 60)

    for expr, expected in expressions:
        result = validate_cel_expression(expr)
        status = "PASS" if result == expected else "FAIL"
        print(f"  [{status}] {expr}")
        print(f"         valid={result} (expected={expected})")
