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
