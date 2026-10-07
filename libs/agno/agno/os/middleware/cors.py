"""Browser origin matching shared by CORS, auth errors and public admission."""

import re
from typing import Optional, Sequence

_LEADING_FLAGS = re.compile(r"\(\?([aiLmsux]+)\)")


def _scoped(pattern: str) -> str:
    # Leading global flags like (?i) are only valid at the start of a whole expression.
    flags = ""
    while match := _LEADING_FLAGS.match(pattern):
        flags += match.group(1)
        pattern = pattern[match.end() :]
    tail = "\n" if "x" in flags else ""  # a trailing verbose comment must not swallow the ")"
    return f"(?{flags}:{pattern}{tail})" if flags else f"(?:{pattern})"


def combine_origin_patterns(patterns: Sequence[str]) -> Optional[str]:
    """Join full-match origin patterns into one expression for Starlette's CORSMiddleware."""
    if not patterns:
        return None
    if len(patterns) == 1:
        return patterns[0]
    combined = "|".join(_scoped(pattern) for pattern in patterns)
    re.compile(combined)
    return combined


class OriginPolicy:
    def __init__(self, origins: Sequence[str], pattern: Optional[str] = None):
        self.origins = tuple(origins)
        self.pattern = pattern
        self._compiled = re.compile(pattern) if pattern is not None else None

    def allows(self, origin: str) -> bool:
        return origin in self.origins or bool(self._compiled and self._compiled.fullmatch(origin))
