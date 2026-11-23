from typing import Literal, Optional

from agno.models.base import Model
from agno.run.base import RunContext


def get_reasoning_agent(
    reasoning_model: Model,
    telemetry: bool = False,
    debug_mode: bool = False,
    debug_level: Literal[1, 2] = 1,
    run_context: Optional[RunContext] = None,
) -> "Agent":  # type: ignore  # noqa: F821
    from agno.agent import Agent

    return Agent(
        model=reasoning_model,
        telemetry=telemetry,
        debug_mode=debug_mode,
        debug_level=debug_level,
        session_state=run_context.session_state if run_context else None,
        dependencies=run_context.dependencies if run_context else None,
        metadata=run_context.metadata if run_context else None,
    )
