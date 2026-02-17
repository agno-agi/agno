# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
#!/usr/bin/env python3
"""
Check Style
=============================

Check Python code for style issues.
"""

import json
import sys


def check_style(code: str) -> dict:
    """Check code for common style issues."""
    issues = []
    lines = code.split("\n")

    for i, line in enumerate(lines, 1):
        # Check line length
        if len(line) > 100:
            issues.append(
                {"line": i, "issue": f"Line exceeds 100 characters ({len(line)})"}
            )

        # Check trailing whitespace
        if line.endswith(" ") or line.endswith("\t"):
            issues.append({"line": i, "issue": "Trailing whitespace"})

        # Check for camelCase variables (simple heuristic)
        if "=" in line and not line.strip().startswith("#"):
            var = line.split("=")[0].strip()
            if (
                any(c.isupper() for c in var)
                and "_" not in var
                and not var[0].isupper()
            ):
                issues.append(
                    {
                        "line": i,
                        "issue": f"Possible camelCase: '{var}' - use snake_case",
                    }
                )

        # Check for single-letter variables
        if "=" in line:
            var = line.split("=")[0].strip()
            if len(var) == 1 and var not in "ijkxyz_":
                issues.append(
                    {
                        "line": i,
                        "issue": f"Single-letter variable '{var}' - use descriptive name",
                    }
                )

    return {
        "total_issues": len(issues),
        "issues": issues,
        "passed": len(issues) == 0,
    }


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        if len(sys.argv) > 1:
            code = sys.argv[1]
        else:
            code = sys.stdin.read()

        result = check_style(code)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
