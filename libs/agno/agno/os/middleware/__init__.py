try:
    from agno.os.middleware.jwt import (
        JWTMiddleware,
        TokenSource,
    )
except ImportError:
    # PyJWT is an optional dependency (agno[os])
    pass

from agno.os.middleware.trailing_slash import TrailingSlashMiddleware

__all__ = [
    name
    for name in (
        "JWTMiddleware",
        "TokenSource",
        "TrailingSlashMiddleware",
    )
    if name in globals()
]
