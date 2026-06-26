from typing import Optional, Union

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.agui.input import merge_tool_results_into_requirements
from agno.run.base import RunContext
from agno.team.remote import RemoteTeam
from agno.team.team import Team


async def resume_paused_run(
    entity: Union[Agent, RemoteAgent, Team, RemoteTeam],
    session_id: str,
    tool_messages: list,
    run_context: RunContext,
    session_state: Optional[dict],
    run_kwargs: dict,
):
    # Load paused run from DB, merge tool results, and call acontinue_run
    if not getattr(entity, "db", None):
        raise ValueError(
            "Frontend tool resume requires a database to be configured on the agent. "
            "Set db=SqliteDb(...) or db=PgDb(...) on your Agent."
        )

    from agno.run.base import RunStatus
    from agno.session.agent import AgentSession

    session = entity.db.get_session(session_id=session_id)  # type: ignore[union-attr]
    if not session:
        raise ValueError(f"Session {session_id} not found")
    if not isinstance(session, AgentSession):
        raise ValueError(f"Session {session_id} is not an AgentSession")

    # Find the paused run (AG-UI sends new run_id on resume, so we find by status)
    paused_run = next(
        (r for r in (session.runs or []) if r.status == RunStatus.paused),
        None,
    )
    if not paused_run:
        raise ValueError(f"No paused run found in session {session_id}")

    if not paused_run.requirements:
        raise ValueError(f"Run {paused_run.run_id} has no requirements to resume")

    # Merge tool results into stored requirements
    requirements = merge_tool_results_into_requirements(paused_run.requirements, tool_messages)

    # Resume the run using the original paused run's ID
    paused_run_id = paused_run.run_id or run_context.run_id
    run_context.run_id = paused_run_id
    return entity.acontinue_run(  # type: ignore
        run_id=paused_run_id,
        session_id=session_id,
        requirements=requirements,
        stream=True,
        stream_events=True,
        session_state=session_state,
        run_context=run_context,
        **run_kwargs,
    )
