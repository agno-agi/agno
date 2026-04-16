"""Workflow factories for per-request, context-driven workflow construction."""

import inspect
import json
from typing import Any, Awaitable, Callable, Optional, Type, Union

from pydantic import BaseModel

from agno.agent.factory import (
    FactoryError,
    FactoryValidationError,
    RequestContext,
)


class WorkflowFactory:
    """A registered callable that produces a Workflow per request.

    Factories live alongside prototype workflows in ``AgentOS(workflows=[...])``.
    On each request, AgentOS invokes the factory with a :class:`RequestContext`
    and uses the returned Workflow for that request.

    Args:
        id: Stable handle used in API URLs (e.g. ``POST /workflows/{id}/runs``).
        factory: Callable that receives a RequestContext and returns a Workflow.
            Both sync and async callables are accepted.
        name: Human-readable name for UI discovery.
        description: Description for UI discovery.
        input_schema: Optional pydantic model describing the expected shape of
            ``factory_input`` in the run request.
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
        """Validate and parse raw factory_input against input_schema."""
        if self.input_schema is None:
            return raw_input

        if raw_input is None:
            raw_input = {}

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
        """Invoke the factory synchronously."""
        if self.is_async():
            raise FactoryError("Cannot invoke async factory synchronously. Use invoke_async() instead.")
        return self.factory(ctx)

    async def invoke_async(self, ctx: RequestContext) -> Any:
        """Invoke the factory, handling both sync and async callables."""
        if self.is_async():
            return await self.factory(ctx)
        return self.factory(ctx)
