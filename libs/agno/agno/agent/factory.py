"""Agent factories for per-request, context-driven agent construction.

Factories enable multi-tenant AgentOS deployments where the agent's tools,
instructions, model, or database scope depend on who is calling.
"""

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Optional, Type, Union

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
    input: Any = None
    trusted: TrustedContext = field(default_factory=TrustedContext)


# ---------------------------------------------------------------------------
# AgentFactory
# ---------------------------------------------------------------------------


class AgentFactory:
    """A registered callable that produces an Agent per request.

    Factories live alongside prototype agents in ``AgentOS(agents=[...])``.
    On each request, AgentOS invokes the factory with a :class:`RequestContext`
    and uses the returned Agent for that request.

    Args:
        id: Stable handle used in API URLs (e.g. ``POST /agents/{id}/runs``).
        factory: Callable that receives a RequestContext and returns an Agent.
            Both sync and async callables are accepted.
        name: Human-readable name for UI discovery.
        description: Description for UI discovery.
        input_schema: Optional pydantic model describing the expected shape of
            ``factory_input`` in the run request. Used for validation and
            OpenAPI schema generation.
    """

    def __init__(
        self,
        id: str,
        factory: Union[Callable[["RequestContext"], Any], Callable[["RequestContext"], Awaitable[Any]]],
        name: Optional[str] = None,
        description: Optional[str] = None,
        input_schema: Optional[Type[BaseModel]] = None,
    ):
        self.id = id
        self.factory = factory
        self.name = name
        self.description = description
        self.input_schema = input_schema

    def validate_input(self, raw_input: Any) -> Any:
        """Validate and parse raw factory_input against input_schema.

        Returns:
            A validated pydantic model instance if input_schema is set,
            otherwise returns the raw input as-is (dict or None).

        Raises:
            FactoryValidationError: If validation fails.
        """
        if self.input_schema is None:
            return raw_input

        if raw_input is None:
            raw_input = {}

        # Parse JSON string if needed
        if isinstance(raw_input, str):
            try:
                raw_input = json.loads(raw_input)
            except (json.JSONDecodeError, TypeError) as e:
                raise FactoryValidationError(f"factory_input is not valid JSON: {e}") from e

        if not isinstance(raw_input, dict):
            raise FactoryValidationError(f"factory_input must be a JSON object, got {type(raw_input).__name__}")

        try:
            return self.input_schema.model_validate(raw_input)
        except Exception as e:
            raise FactoryValidationError(f"factory_input validation failed: {e}") from e

    def is_async(self) -> bool:
        """Check if the factory callable is async."""
        return inspect.iscoroutinefunction(self.factory)

    def invoke(self, ctx: RequestContext) -> Any:
        """Invoke the factory synchronously. Raises if factory is async."""
        if self.is_async():
            raise FactoryError("Cannot invoke async factory synchronously. Use invoke_async() instead.")
        return self.factory(ctx)

    async def invoke_async(self, ctx: RequestContext) -> Any:
        """Invoke the factory, handling both sync and async callables."""
        if self.is_async():
            return await self.factory(ctx)
        return self.factory(ctx)
