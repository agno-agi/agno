"""Utils for our multiple integrations with external code execution environments."""

import re


def prepare_python_code(code: str) -> str:
    """Fix common problems with LLM-generated Python code."""
    python_keywords = {"true": "True", "false": "False", "none": "None"}
    for lowercase, capitalized in python_keywords.items():
        code = re.sub(rf"\b({lowercase})\b", capitalized, code)
    return code
