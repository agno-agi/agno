from typing import List, Union

from ag_ui.core.types import ToolMessage as AGUIToolMessage

from agno.agent import Agent
from agno.os.interfaces.agui.input import ensure_requirements_resolved, merge_tool_results_into_requirements
from agno.run.base import RunContext
from agno.team.team import Team


async def resume_paused_run(
    entity: Union[Agent, Team],
    session_id: str,
    tool_messages: List[AGUIToolMessage],
    run_context: RunContext,
    run_kwargs: dict,
):
    # Remote entities don't support client_tools resume (no aget_session)
    if not getattr(entity, "db", None):
        raise ValueError(
            "Frontend tool resume requires a database. "
            "Set db=SqliteDb(...) or db=PgDb(...) on your Agent/Team."
        )

    from agno.run.base import RunStatus
    from agno.session.agent import AgentSession
    from agno.session.team import TeamSession

    session = await entity.aget_session(session_id=session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")
    if not isinstance(session, (AgentSession, TeamSession)):
        raise ValueError(f"Session {session_id} is not a valid session type")

    # Find the paused run (AG-UI sends new run_id on resume, so we find by status)
    paused_run = next(
        (r for r in (session.runs or []) if r.status == RunStatus.paused),
        None,
    )
    if not paused_run:
        raise ValueError(f"No paused run found in session {session_id}")

    if not paused_run.requirements:
        raise ValueError(f"Run {paused_run.run_id} has no requirements to resume")

    # Merge tool results; refuse a partial multi-tool answer (an unanswered tool would be silently rejected at dispatch).
    requirements = merge_tool_results_into_requirements(paused_run.requirements, tool_messages)
    ensure_requirements_resolved(requirements)

    # Resume the run using the original paused run's ID
    paused_run_id = paused_run.run_id or run_context.run_id
    run_context.run_id = paused_run_id
    return entity.acontinue_run(  # type: ignore
        run_id=paused_run_id,
        session_id=session_id,
        requirements=requirements,
        stream=True,
        stream_events=True,
        run_context=run_context,
        **run_kwargs,
    )
