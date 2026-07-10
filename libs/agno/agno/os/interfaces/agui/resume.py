from typing import Any, Dict, List, Optional, Union

from ag_ui.core.types import ToolMessage as AGUIToolMessage

from agno.agent import Agent
from agno.run.base import RunContext, RunStatus
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.team.team import Team
from agno.utils.string import parse_response_dict_str


def _resolve_confirmation(requirement: RunRequirement, payload: Dict[str, Any], error: Optional[str]) -> None:
    if error or payload.get("accepted") is not True:
        requirement.reject(note=payload.get("note") or error)
    else:
        requirement.confirm()


def _resolve_user_input(requirement: RunRequirement, payload: Dict[str, Any]) -> None:
    values = payload.get("values")
    if not isinstance(values, dict):
        raise ValueError("user_input expects {'values': {...}}")
    requirement.provide_user_input(values)


def _resolve_user_feedback(requirement: RunRequirement, payload: Dict[str, Any]) -> None:
    selections = payload.get("selections")
    if not isinstance(selections, dict) or not all(isinstance(v, list) for v in selections.values()):
        raise ValueError("user_feedback expects {'selections': {question: [labels]}}")
    requirement.provide_user_feedback(selections)


def _resolve_external_execution(requirement: RunRequirement, content: str, error: Optional[str]) -> None:
    if error and requirement.tool_execution:
        requirement.tool_execution.tool_call_error = True
    requirement.set_external_execution_result(error or content)


def resolve_requirements_from_tool_messages(
    requirements: List[RunRequirement],
    tool_messages: List[AGUIToolMessage],
) -> List[RunRequirement]:
    tool_message_by_call_id = {msg.tool_call_id: msg for msg in tool_messages}

    for requirement in requirements:
        if requirement.is_resolved():
            continue

        tool_exec = requirement.tool_execution
        if not tool_exec or not tool_exec.tool_call_id:
            continue

        tool_message = tool_message_by_call_id.get(tool_exec.tool_call_id)
        if tool_message is None:
            continue

        # External execution: raw content, no JSON parsing
        if requirement.pause_type == "external_execution":
            _resolve_external_execution(requirement, tool_message.content, tool_message.error)
            continue

        # Structured pause types: parse JSON payload
        parsed = parse_response_dict_str(tool_message.content)
        payload: Dict[str, Any] = parsed if isinstance(parsed, dict) else {}

        if requirement.pause_type == "confirmation":
            _resolve_confirmation(requirement, payload, tool_message.error)
        elif requirement.pause_type == "user_input":
            _resolve_user_input(requirement, payload)
        elif requirement.pause_type == "user_feedback":
            _resolve_user_feedback(requirement, payload)

    return requirements


def ensure_requirements_resolved(requirements: List[RunRequirement]) -> None:
    """Guard: raise if any requirement is still unresolved after merging tool messages.

    A partial resume (some tools answered, some not) must fail loud here rather than
    reach dispatch where unanswered confirmation tools are silently rejected.
    """
    unresolved = [r for r in requirements if not r.is_resolved()]
    if unresolved:
        ids = [r.tool_execution.tool_call_id for r in unresolved if r.tool_execution]
        raise ValueError(f"Partial resume: requirements {ids} still unresolved")


def _find_paused_run(
    session: Union[AgentSession, TeamSession],
    tool_messages: List[AGUIToolMessage],
    is_team: bool,
):
    incoming_call_ids = {msg.tool_call_id for msg in tool_messages}

    for run in session.runs or []:
        if is_team and not isinstance(run, TeamRunOutput):
            continue
        if run.status != RunStatus.paused:
            continue
        for req in run.requirements or []:
            if req.tool_execution and req.tool_execution.tool_call_id in incoming_call_ids:
                return run

    return None


async def resume_paused_run(
    entity: Union[Agent, Team],
    session_id: str,
    tool_messages: List[AGUIToolMessage],
    run_context: RunContext,
    run_kwargs: dict,
):
    if not isinstance(entity, (Agent, Team)):
        raise ValueError("Frontend tool resume requires a local Agent or Team")
    if not entity.db:
        raise ValueError("Frontend tool resume requires a database")

    session = await entity.aget_session(session_id=session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")
    if not isinstance(session, (AgentSession, TeamSession)):
        raise ValueError(f"Session {session_id} is not a valid session type")

    paused_run = _find_paused_run(session, tool_messages, is_team=isinstance(entity, Team))
    if not paused_run:
        raise ValueError(f"No paused run matching the provided tool results found in session {session_id}")
    if not paused_run.requirements:
        raise ValueError(f"Run {paused_run.run_id} has no requirements to resume")

    requirements = resolve_requirements_from_tool_messages(paused_run.requirements, tool_messages)

    if paused_run.run_id:
        run_context.run_id = paused_run.run_id

    return entity.acontinue_run(  # type: ignore
        run_id=paused_run.run_id,
        session_id=session_id,
        requirements=requirements,
        stream=True,
        stream_events=True,
        run_context=run_context,
        **run_kwargs,
    )
