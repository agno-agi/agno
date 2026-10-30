"""Utils for our multiple integrations with external code execution environments."""

import re

# LLMs emit the JSON/JavaScript spellings of the Python constants in generated code.
_KEYWORD_REPLACEMENTS = {"true": "True", "false": "False", "none": "None"}

# String literals and comments are matched as whole tokens, ahead of the keyword
# alternative, so their contents are never rewritten: only a bare ``true`` is a keyword,
# while ``"true"`` is data the program means to keep verbatim.
_CODE_TOKEN_RE = re.compile(
    r"""
      [A-Za-z]{0,2}
      (?:
          '''[\s\S]*?'''
        | \"\"\"[\s\S]*?\"\"\"
        | '(?:\\.|[^'\\])*'
        | "(?:\\.|[^"\\])*"
      )
    | \#[^\n]*
    | \b(?:true|false|none)\b
    """,
    re.VERBOSE,
)


def _replace_keyword(match: re.Match) -> str:
    # Literals and comments always come back with their delimiters, so they can never
    # equal a bare keyword and fall straight through the lookup below.
    token = match.group()
    return _KEYWORD_REPLACEMENTS.get(token, token)


def prepare_python_code(code: str) -> str:
    """Fix common problems with LLM-generated Python code."""
    return _CODE_TOKEN_RE.sub(_replace_keyword, code)
