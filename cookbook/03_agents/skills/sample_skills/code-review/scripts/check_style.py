"""Style checker script for code review.

This script provides utilities for checking code style compliance.
"""


def check_naming_conventions(code: str) -> list[dict]:
    """Check for common naming convention issues.

    Args:
        code: The Python code to check.

    Returns:
        A list of issues found, each with line number and description.
    """
    issues = []
    lines = code.split("\n")

    for i, line in enumerate(lines, 1):
        # Check for camelCase variable names (simple heuristic)
        if "=" in line and not line.strip().startswith("#"):
            parts = line.split("=")[0].strip()
            if any(c.isupper() for c in parts) and "_" not in parts:
                if not parts[0].isupper():  # Not a class
                    issues.append(
                        {
                            "line": i,
                            "type": "naming",
                            "message": f"Possible camelCase variable: '{parts}'. Use snake_case instead.",
                        }
                    )

        # Check for single-letter variable names (except i, j, k, x, y, z)
        if "=" in line:
            var_name = line.split("=")[0].strip()
            if len(var_name) == 1 and var_name not in "ijkxyz_":
                issues.append(
                    {
                        "line": i,
                        "type": "naming",
                        "message": f"Single-letter variable '{var_name}'. Use descriptive names.",
                    }
                )

    return issues


def check_function_length(code: str, max_lines: int = 50) -> list[dict]:
    """Check for functions that are too long.

    Args:
        code: The Python code to check.
        max_lines: Maximum allowed lines per function.

    Returns:
        A list of issues for functions exceeding the limit.
    """
    issues = []
    lines = code.split("\n")
    in_function = False
    function_name = ""
    function_start = 0
    function_lines = 0
    indent_level = 0

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        if stripped.startswith("def "):
            if in_function and function_lines > max_lines:
                issues.append(
                    {
                        "line": function_start,
                        "type": "length",
                        "message": f"Function '{function_name}' is {function_lines} lines (max: {max_lines}).",
                    }
                )

            in_function = True
            function_name = stripped.split("(")[0].replace("def ", "")
            function_start = i
            function_lines = 1
            indent_level = len(line) - len(line.lstrip())

        elif in_function:
            if stripped and not stripped.startswith("#"):
                current_indent = len(line) - len(line.lstrip())
                if current_indent <= indent_level and not stripped.startswith("def "):
                    in_function = False
                else:
                    function_lines += 1

    # Check last function
    if in_function and function_lines > max_lines:
        issues.append(
            {
                "line": function_start,
                "type": "length",
                "message": f"Function '{function_name}' is {function_lines} lines (max: {max_lines}).",
            }
        )

    return issues


def run_style_check(code: str) -> dict:
    """Run all style checks on the given code.

    Args:
        code: The Python code to check.

    Returns:
        A dictionary with check results and summary.
    """
    naming_issues = check_naming_conventions(code)
    length_issues = check_function_length(code)

    all_issues = naming_issues + length_issues
    all_issues.sort(key=lambda x: x["line"])

    return {
        "total_issues": len(all_issues),
        "naming_issues": len(naming_issues),
        "length_issues": len(length_issues),
        "issues": all_issues,
        "passed": len(all_issues) == 0,
    }
