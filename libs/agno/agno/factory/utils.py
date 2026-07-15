"""Request context and exceptions for factory invocations."""

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Union

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FactoryError(Exception):
    """Base exception for factory errors. Maps to HTTP 500."""

    pass


class FactoryValidationError(FactoryError):
    """factory_input failed validation against input_schema. Maps to HTTP 400."""

    pass


class FactoryPermissionError(FactoryError):
    """Factory decided the caller is not authorized. Maps to HTTP 403."""

    pass


class FactoryContextRequired(FactoryError):
    """A factory was encountered but no RequestContext was provided."""

    pass


# ---------------------------------------------------------------------------
# Request context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrustedContext:
    """Context populated by verified middleware only (e.g. JWT claims).

    Nothing the client can set directly lands here. The factory must use
    this for authorization decisions (e.g. which tools to grant).
    """

    claims: Mapping[str, Any] = field(default_factory=dict)
    scopes: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class RequestContext:
    """The single object threaded into every factory call.

    Attributes:
        user_id: From form field or request.state (same precedence as today).
        session_id: From form field or request.state.
        request: Raw FastAPI Request — escape hatch for anything not plumbed through.
        input: Validated factory_input (pydantic model if input_schema was set, else dict).
        trusted: Populated by verified middleware only (request.state.*).
    """

    user_id: Optional[str] = None
    session_id: Optional[str] = None
    request: Any = None  # fastapi.Request — typed as Any to avoid hard dependency at import time
    input: Optional[Union[BaseModel, Dict[str, Any]]] = None
    trusted: TrustedContext = field(default_factory=TrustedContext)
