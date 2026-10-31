"""Browser origin matching shared by CORS, auth errors and public admission."""

import re
from typing import Collection, Sequence

from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp


class OriginPolicy:
    def __init__(self, origins: Sequence[str], patterns: Sequence[str] = ()):
        self.origins = tuple(origins)
        self.patterns = tuple(patterns)
        self._compiled = tuple(re.compile(pattern) for pattern in self.patterns)

    def allows(self, origin: str) -> bool:
        return origin in self.origins or any(pattern.fullmatch(origin) for pattern in self._compiled)


class OriginPolicyCORSMiddleware(CORSMiddleware):
    """CORSMiddleware for several origin patterns, each matched independently.

    Starlette accepts a single ``allow_origin_regex``; joining patterns into one
    expression breaks valid patterns that share group names or use backreferences.
    """

    def __init__(
        self,
        app: ASGIApp,
        origin_policy: OriginPolicy,
        allow_methods: Collection[str] = ("GET",),
        allow_headers: Collection[str] = (),
        allow_credentials: bool = False,
        expose_headers: Collection[str] = (),
    ) -> None:
        super().__init__(
            app,
            allow_origins=list(origin_policy.origins),
            allow_methods=allow_methods,
            allow_headers=allow_headers,
            allow_credentials=allow_credentials,
            expose_headers=expose_headers,
        )
        self.origin_policy = origin_policy

    def is_allowed_origin(self, origin: str) -> bool:
        return self.origin_policy.allows(origin)
