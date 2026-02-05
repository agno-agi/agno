def test_team_module_reexports_run_types() -> None:
    from agno.run.team import (
        TeamRunEvent as CanonicalTeamRunEvent,
    )
    from agno.run.team import (
        TeamRunInput as CanonicalTeamRunInput,
    )
    from agno.run.team import (
        TeamRunOutput as CanonicalTeamRunOutput,
    )
    from agno.run.team import (
        TeamRunOutputEvent as CanonicalTeamRunOutputEvent,
    )
    from agno.team.team import TeamRunEvent, TeamRunInput, TeamRunOutput, TeamRunOutputEvent

    assert TeamRunEvent is CanonicalTeamRunEvent
    assert TeamRunInput is CanonicalTeamRunInput
    assert TeamRunOutput is CanonicalTeamRunOutput
    assert TeamRunOutputEvent is CanonicalTeamRunOutputEvent
