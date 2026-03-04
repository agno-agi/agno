"""Utils for our multiple integrations with external code execution environments."""

import io
import re
import token
import tokenize

_KEYWORD_MAP = {"true": "True", "false": "False", "none": "None"}


def prepare_python_code(code: str) -> str:
    """Fix common problems with LLM-generated Python code.

    Replaces bare true/false/none NAME tokens with their Python equivalents
    (True/False/None) without corrupting string literals or comments.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(code).readline))
    except tokenize.TokenError:
        return _prepare_python_code_fallback(code)

    modified = []
    for tok in tokens:
        if tok.type == token.NAME and tok.string in _KEYWORD_MAP:
            modified.append(tok._replace(string=_KEYWORD_MAP[tok.string]))
        else:
            modified.append(tok)

    return tokenize.untokenize(modified)


def _prepare_python_code_fallback(code: str) -> str:
    """Regex fallback for code that fails to tokenize (e.g. syntax errors)."""
    for lowercase, capitalized in _KEYWORD_MAP.items():
        code = re.sub(rf"\b({lowercase})\b", capitalized, code)
    return code
