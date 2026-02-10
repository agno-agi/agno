try:
    from agno.os.middleware.jwt import (
        JWTMiddleware,
        TokenSource,
    )
except ImportError:

    class JWTMiddleware:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "`PyJWT` not installed. Please install using `pip install 'agno[os]'` or `pip install PyJWT`"
            )

    class TokenSource:  # type: ignore
        pass


from agno.os.middleware.trailing_slash import TrailingSlashMiddleware

__all__ = [
    "JWTMiddleware",
    "TokenSource",
    "TrailingSlashMiddleware",
]
