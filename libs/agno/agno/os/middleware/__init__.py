try:
    from agno.os.middleware.jwt import (
        JWTIssuer,
        JWTMiddleware,
        JWTValidator,
        TokenSource,
    )
except ImportError:
    _PYJWT_MISSING = (
        "PyJWT is not installed. Please install using `pip install 'agno[os]'` or `pip install PyJWT`"
    )

    class JWTMiddleware:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError(_PYJWT_MISSING)

    class TokenSource:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError(_PYJWT_MISSING)

    class JWTValidator:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError(_PYJWT_MISSING)

    class JWTIssuer:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError(_PYJWT_MISSING)


from agno.os.middleware.trailing_slash import TrailingSlashMiddleware

__all__ = [
    name
    for name in (
        "JWTMiddleware",
        "JWTValidator",
        "JWTIssuer",
        "TokenSource",
        "TrailingSlashMiddleware",
    )
    if name in globals()
]
