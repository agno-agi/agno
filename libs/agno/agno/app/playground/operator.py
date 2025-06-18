from typing import Any, List, Optional, Union, cast

from agno.agent.agent import Agent, AgentRun, Function, Toolkit
from agno.run.response import RunResponse
from agno.run.team import TeamRunResponse
from agno.storage.session.agent import AgentSession
from agno.storage.session.team import TeamSession
from agno.storage.session.workflow import WorkflowSession
from agno.team.team import Team
from agno.utils.log import logger
from agno.workflow.workflow import Workflow


def format_tools(agent_tools):
    formatted_tools = []
    if agent_tools is not None:
        for tool in agent_tools:
            if isinstance(tool, dict):
                formatted_tools.append(tool)
            elif isinstance(tool, Toolkit):
                for _, f in tool.functions.items():
                    formatted_tools.append(f.to_dict())
            elif isinstance(tool, Function):
                formatted_tools.append(tool.to_dict())
            elif callable(tool):
                func = Function.from_callable(tool)
                formatted_tools.append(func.to_dict())
            else:
                logger.warning(f"Unknown tool type: {type(tool)}")
    return formatted_tools


def get_agent_by_id(agent_id: str, agents: Optional[List[Agent]] = None) -> Optional[Agent]:
    if agent_id is None or agents is None:
        return None

    for agent in agents:
        if agent.agent_id == agent_id:
            return agent
    return None


def get_session_title(session: Union[AgentSession, TeamSession]) -> str:
    if session is None:
        return "Unnamed session"
    session_name = session.session_data.get("session_name") if session.session_data is not None else None
    if session_name is not None:
        return session_name
    memory = session.memory
    if memory is not None:
        # Proxy for knowing it is legacy memory implementation
        runs = memory.get("runs")
        runs = cast(List[Any], runs)

        for _run in runs:
            try:
                if "response" in _run:
                    run_parsed = AgentRun.model_validate(_run)
                    if run_parsed.message is not None and run_parsed.message.role == "user":
                        content = run_parsed.message.get_content_string()
                        if content:
                            return content
                        else:
                            return "No title"
                else:
                    if "agent_id" in _run:
                        run_response_parsed = RunResponse.from_dict(_run)
                    else:
                        run_response_parsed = TeamRunResponse.from_dict(_run)  # type: ignore
                    if run_response_parsed.messages is not None and len(run_response_parsed.messages) > 0:
                        for msg in run_response_parsed.messages:
                            if msg.role == "user":
                                content = msg.get_content_string()
                                if content:
                                    return content

            except Exception as e:
                import traceback

                traceback.print_exc(limit=3)

                logger.error(f"Error parsing chat: {e}")

    return "Unnamed session"


def get_session_title_from_workflow_session(workflow_session: WorkflowSession) -> str:
    if workflow_session is None:
        return "Unnamed session"
    session_name = (
        workflow_session.session_data.get("session_name") if workflow_session.session_data is not None else None
    )
    if session_name is not None:
        return session_name
    memory = workflow_session.memory
    if memory is not None:
        runs = memory.get("runs")
        runs = cast(List[Any], runs)
        for _run in runs:
            try:
                # Try to get content directly from the run first (workflow structure)
                content = _run.get("content")
                if content:
                    # Split content by newlines and take first line, but limit to 100 chars
                    first_line = content.split("\n")[0]
                    return first_line[:100] + "..." if len(first_line) > 100 else first_line

                # Fallback to response.content structure (if it exists)
                response = _run.get("response")
                if response:
                    content = response.get("content")
                    if content:
                        # Split content by newlines and take first line, but limit to 100 chars
                        first_line = content.split("\n")[0]
                        return first_line[:100] + "..." if len(first_line) > 100 else first_line

            except Exception as e:
                logger.error(f"Error parsing workflow session: {e}")
    return "Unnamed session"


def get_workflow_by_id(workflow_id: str, workflows: Optional[List[Workflow]] = None) -> Optional[Workflow]:
    if workflows is None or workflow_id is None:
        return None

    for workflow in workflows:
        if workflow.workflow_id == workflow_id:
            return workflow
    return None


def get_team_by_id(team_id: str, teams: Optional[List[Team]] = None) -> Optional[Team]:
    if teams is None or team_id is None:
        return None

    for team in teams:
        if team.team_id == team_id:
            return team
    return None


def get_session_title_from_team_session(team_session: TeamSession) -> str:
    if team_session is None:
        return "Unnamed session"
    session_name = team_session.session_data.get("session_name") if team_session.session_data is not None else None
    if session_name is not None:
        return session_name
    memory = team_session.memory
    if memory is not None:
        runs = memory.get("runs")
        runs = cast(List[Any], runs)

        for _run in runs:
            try:
                if "response" in _run:
                    run_parsed = AgentRun.model_validate(_run)
                    if run_parsed.message is not None and run_parsed.message.role == "user":
                        content = run_parsed.message.get_content_string()
                        if content:
                            return content
                        else:
                            return "No title"
                else:
                    if "agent_id" in _run:
                        run_response_parsed = RunResponse.from_dict(_run)
                    else:
                        run_response_parsed = TeamRunResponse.from_dict(_run)  # type: ignore
                    if run_response_parsed.messages is not None and len(run_response_parsed.messages) > 0:
                        for msg in run_response_parsed.messages:
                            if msg.role == "user":
                                content = msg.get_content_string()
                                if content:
                                    return content

            except Exception as e:
                logger.error(f"Error parsing chat: {e}")
    return "Unnamed session"
