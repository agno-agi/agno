"""Verify that public symbols are importable from agno.agent and agno.agent.agent."""

import agno.agent as agent_pkg


def test_agent_module_reexports_run_types() -> None:
    from agno.agent.agent import RunInput, RunOutput, RunOutputEvent
    from agno.run.agent import (
        RunInput as CanonicalRunInput,
    )
    from agno.run.agent import (
        RunOutput as CanonicalRunOutput,
    )
    from agno.run.agent import (
        RunOutputEvent as CanonicalRunOutputEvent,
    )

    assert RunInput is CanonicalRunInput
    assert RunOutput is CanonicalRunOutput
    assert RunOutputEvent is CanonicalRunOutputEvent


def test_agent_package_exports_all_symbols() -> None:
    """Every symbol listed in agno.agent.__all__ must be importable."""
    missing = []
    for name in agent_pkg.__all__:
        if not hasattr(agent_pkg, name):
            missing.append(name)
    assert missing == [], f"agno.agent.__all__ contains symbols that are not importable: {missing}"


def test_agent_package_exports_expected_symbols() -> None:
    """Ensure the known public API symbols are present in agno.agent.__all__."""
    expected = {
        "Agent",
        "RemoteAgent",
        "AgentSession",
        "Function",
        "Message",
        "Toolkit",
        "RunEvent",
        "RunOutput",
        "RunOutputEvent",
        "RunContentEvent",
        "RunCancelledEvent",
        "RunErrorEvent",
        "RunPausedEvent",
        "RunContinuedEvent",
        "RunStartedEvent",
        "RunCompletedEvent",
        "MemoryUpdateStartedEvent",
        "MemoryUpdateCompletedEvent",
        "ReasoningStartedEvent",
        "ReasoningStepEvent",
        "ReasoningCompletedEvent",
        "ToolCallStartedEvent",
        "ToolCallCompletedEvent",
    }
    actual = set(agent_pkg.__all__)
    missing = expected - actual
    assert missing == set(), f"Expected symbols missing from agno.agent.__all__: {missing}"
