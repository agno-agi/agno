from typing import Any, Dict, List, Optional, Union

from ag_ui.core.types import ToolMessage as AGUIToolMessage

from agno.agent import Agent
from agno.run.agent import RunOutput
from agno.run.base import RunContext, RunStatus
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.team.team import Team
from agno.utils.string import parse_response_dict_str


def _resolve_confirmation(req: RunRequirement, data: Dict[str, Any], error: Optional[str]) -> None:
    if error or data.get("accepted") is not True:
        req.reject(note=data.get("note") or error)
    else:
        req.confirm()


def _resolve_user_input(req: RunRequirement, data: Dict[str, Any], error: Optional[str]) -> None:
    values = data.get("values")
    if not isinstance(values, dict):
        raise ValueError("user_input expects {'values': {...}}")
    req.provide_user_input(values)


def _resolve_user_feedback(req: RunRequirement, data: Dict[str, Any], error: Optional[str]) -> None:
    selections = data.get("selections")
    if not isinstance(selections, dict) or not all(isinstance(v, list) for v in selections.values()):
        raise ValueError("user_feedback expects {'selections': {question: [labels]}}")
    req.provide_user_feedback(selections)


def _resolve_external_execution(req: RunRequirement, data: Dict[str, Any], error: Optional[str], content: str) -> None:
    if error and req.tool_execution:
        req.tool_execution.tool_call_error = True
    req.set_external_execution_result(error if error else content)


def merge_tool_results_into_requirements(
    requirements: List[RunRequirement],
    tool_messages: List[AGUIToolMessage],
) -> List[RunRequirement]:
    """Match ToolMessages to requirements by tool_call_id and resolve each by pause_type."""
    results_map = {tm.tool_call_id: (tm.content, getattr(tm, "error", None)) for tm in tool_messages}

    for req in requirements:
        if req.is_resolved():
            continue
        te = req.tool_execution
        if not te or not te.tool_call_id or te.tool_call_id not in results_map:
            continue

        content, error = results_map[te.tool_call_id]
        data = parse_response_dict_str(content) or {}

        if req.pause_type == "confirmation":
            _resolve_confirmation(req, data, error)
        elif req.pause_type == "user_input":
            _resolve_user_input(req, data, error)
        elif req.pause_type == "user_feedback":
            _resolve_user_feedback(req, data, error)
        elif req.pause_type == "external_execution":
            _resolve_external_execution(req, data, error, content)

    return requirements


async def resume_paused_run(
    entity: Union[Agent, Team],
    session_id: str,
    tool_messages: List[AGUIToolMessage],
    run_context: RunContext,
    run_kwargs: dict,
):
    """Resume a paused run by applying frontend tool results and continuing."""
    # Remote entities don't support client_tools resume (no aget_session)
    if not isinstance(entity, (Agent, Team)):
        raise ValueError(
            "Frontend tool resume requires a local Agent or Team. RemoteAgent/RemoteTeam are not supported."
        )
    if not getattr(entity, "db", None):
        raise ValueError(
            "Frontend tool resume requires a database. Set db=SqliteDb(...) or db=PgDb(...) on your Agent/Team."
        )

    session = await entity.aget_session(session_id=session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")
    if not isinstance(session, (AgentSession, TeamSession)):
        raise ValueError(f"Session {session_id} is not a valid session type")

    # Find the paused run. Match on tool_call_ids: the session may hold multiple paused runs
    # (e.g. one the user abandoned), and the incoming results identify which run is being resumed.
    # For Teams, resume the top-level TeamRunOutput, not member runs (whose missing team_id crashes core).
    incoming_tool_call_ids = {tm.tool_call_id for tm in tool_messages}
    paused_run: Union[RunOutput, TeamRunOutput, None] = None

    def matches_tool_messages(run) -> bool:
        return any(
            req.tool_execution and req.tool_execution.tool_call_id in incoming_tool_call_ids
            for req in (run.requirements or [])
        )

    if isinstance(entity, Team):
        paused_run = next(
            (
                r
                for r in (session.runs or [])
                if r.status == RunStatus.paused and isinstance(r, TeamRunOutput) and matches_tool_messages(r)
            ),
            None,
        )
    else:
        paused_run = next(
            (r for r in (session.runs or []) if r.status == RunStatus.paused and matches_tool_messages(r)),
            None,
        )
    if not paused_run:
        raise ValueError(f"No paused run matching the provided tool results found in session {session_id}")

    if not paused_run.requirements:
        raise ValueError(f"Run {paused_run.run_id} has no requirements to resume")

    # Merge tool results by pause_type
    requirements = merge_tool_results_into_requirements(paused_run.requirements, tool_messages)

    # Continue under the original run_id, not the new one AG-UI generated for this resume request
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
