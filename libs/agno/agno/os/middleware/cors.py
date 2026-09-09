"""Browser origin matching shared by CORS, auth errors and public admission."""

import re
from typing import Optional, Sequence


class OriginPolicy:
    def __init__(self, origins: Sequence[str], pattern: Optional[str] = None):
        self.origins = tuple(origins)
        self.pattern = pattern
        self._compiled = re.compile(pattern) if pattern is not None else None

    def allows(self, origin: str) -> bool:
        return origin in self.origins or bool(self._compiled and self._compiled.fullmatch(origin))
