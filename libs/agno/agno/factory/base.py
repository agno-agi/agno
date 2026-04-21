"""Base factory for per-request, context-driven component construction."""

import inspect
import json
from dataclasses import replace
from typing import Any, Awaitable, Callable, Generic, Optional, Type, TypeVar, Union

from pydantic import BaseModel

from agno.factory.utils import (
    FactoryError,
    FactoryValidationError,
    RequestContext,
)

T = TypeVar("T")  # The component type produced by the factory (Agent, Team, or Workflow)


class BaseFactory(Generic[T]):
    """Base class for all factory types (Agent, Team, Workflow).

    A factory is a registered callable that AgentOS invokes on each request
    with a :class:`RequestContext`, returning a freshly built component.

    Type parameter T is the component type produced by the factory.

    Args:
        id: Stable handle used in API URLs (e.g. ``POST /agents/{id}/runs``).
        factory: Callable that receives a RequestContext and returns a component of type T.
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
        factory: Union[Callable[["RequestContext"], T], Callable[["RequestContext"], Awaitable[T]]],
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

    def invoke(self, ctx: RequestContext) -> T:
        """Invoke the factory synchronously. Raises if factory is async."""
        if self.is_async():
            raise FactoryError("Cannot invoke async factory synchronously. Use invoke_async() instead.")
        return self.factory(ctx)  # type: ignore[return-value]

    async def invoke_async(self, ctx: RequestContext) -> T:
        """Invoke the factory, handling both sync and async callables."""
        if self.is_async():
            return await self.factory(ctx)  # type: ignore[misc,return-value]
        return self.factory(ctx)  # type: ignore[return-value]

    def _set_factory_id(self, component: T) -> None:
        """Set factory_id on the produced component (Agent, Team, or Workflow).

        This is picked up by RunOutput (via getattr(agent, "factory_id", None)),
        then propagated to all SSE events by handle_event() in utils/events.py.
        The FE uses factory_id to match SSE events to the selected factory
        (see useStreamSessionResolver.ts).

        The factory author's original component.id is preserved for session keying.
        """
        component.factory_id = self.id  # type: ignore[attr-defined]

    def resolve(self, ctx: RequestContext, expected_type: Type[T]) -> T:
        """Validate input, invoke the factory, and type-check the result.

        Full resolution flow:
        1. Validates ctx.input against input_schema (if set)
        2. Invokes the factory callable with the validated context
        3. Checks the return type matches expected_type (Agent, Team, or Workflow)
        4. Sets factory_id on the result for SSE event matching

        Args:
            ctx: The request context (input will be validated and replaced).
            expected_type: The expected return type (Agent, Team, or Workflow).

        Returns:
            The produced component (Agent, Team, or Workflow) with factory_id set.
        """
        validated_input = self.validate_input(ctx.input)
        ctx_with_input = replace(ctx, input=validated_input)
        result = self.invoke(ctx_with_input)
        if not isinstance(result, expected_type):
            raise FactoryError(
                f"{type(self).__name__} '{self.id}' returned {type(result).__name__}, expected {expected_type.__name__}."
            )
        self._set_factory_id(result)
        return result

    async def resolve_async(self, ctx: RequestContext, expected_type: Type[T]) -> T:
        """Async variant of resolve — supports both sync and async factory callables."""
        validated_input = self.validate_input(ctx.input)
        ctx_with_input = replace(ctx, input=validated_input)
        result = await self.invoke_async(ctx_with_input)
        if not isinstance(result, expected_type):
            raise FactoryError(
                f"{type(self).__name__} '{self.id}' returned {type(result).__name__}, expected {expected_type.__name__}."
            )
        self._set_factory_id(result)
        return result
