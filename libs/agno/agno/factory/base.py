"""Base factory for per-request, context-driven component construction."""

import inspect
import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Generic, Optional, Type, TypeVar, Union

from pydantic import BaseModel

if TYPE_CHECKING:
    from agno.db.base import AsyncBaseDb, BaseDb

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
            The produced component's id will be enforced to match this.
        db: Database for session storage. Required — the FE needs db_id for requests.
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
        db: Union["BaseDb", "AsyncBaseDb"],
        factory: Union[Callable[["RequestContext"], T], Callable[["RequestContext"], Awaitable[T]]],
        name: Optional[str] = None,
        description: Optional[str] = None,
        input_schema: Optional[Type[BaseModel]] = None,
    ):
        if not id:
            raise ValueError("BaseFactory requires a non-empty 'id' argument.")
        if db is None:
            raise ValueError("BaseFactory requires a 'db' argument for session storage.")
        self.id = id
        self.db = db
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

    def _post_resolve(self, component: T) -> None:
        """Post-resolve setup for the produced component.

        Enforces that the produced component's id matches the factory's registration id.
        If the factory author set a different id, log a warning and override it.
        Also sets the db from the factory if the component doesn't have one.

        Subclasses override this to add component-specific initialization
        (e.g. initialize_agent(), initialize_team(), store_events).
        """
        if component.id is not None and component.id != self.id:  # type: ignore[attr-defined]
            from agno.utils.log import log_warning

            log_warning(
                f"Factory '{self.id}': produced component has id='{component.id}', "  # type: ignore[attr-defined]
                f"overriding to match factory id='{self.id}'. "
                "The component id must match the factory id for session storage and FE matching."
            )
        component.id = self.id  # type: ignore[attr-defined]

        # Set db from factory if component doesn't have one
        if not getattr(component, "db", None) and self.db:
            component.db = self.db  # type: ignore[attr-defined]

        component.store_events = True  # type: ignore[attr-defined]

    def resolve(self, ctx: RequestContext, expected_type: Type[T]) -> T:
        """Validate input, invoke the factory, and type-check the result.

        Full resolution flow:
        1. Validates ctx.input against input_schema (if set)
        2. Invokes the factory callable with the validated context
        3. Checks the return type matches expected_type (Agent, Team, or Workflow)
        4. Enforces component.id matches factory.id, sets db, initializes component

        Args:
            ctx: The request context (input will be validated and replaced).
            expected_type: The expected return type (Agent, Team, or Workflow).

        Returns:
            The produced component, initialized and ready to run.
        """
        validated_input = self.validate_input(ctx.input)
        ctx_with_input = replace(ctx, input=validated_input)
        result = self.invoke(ctx_with_input)
        if not isinstance(result, expected_type):
            raise FactoryError(
                f"{type(self).__name__} '{self.id}' returned {type(result).__name__}, expected {expected_type.__name__}."
            )
        self._post_resolve(result)
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
        self._post_resolve(result)
        return result
