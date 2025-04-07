from typing import Any, List, Optional, Union, cast

from agno.agent.agent import Agent, AgentRun, Function, Toolkit
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
                for f_name, f in tool.functions.items():
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
        runs = memory.get("runs") or memory.get("chats")
        runs = cast(List[Any], runs)
        for _run in runs:
            try:
                run_parsed = AgentRun.model_validate(_run)
                if run_parsed.message is not None and run_parsed.message.role == "user":
                    content = run_parsed.message.get_content_string()
                    if content:
                        return content
                    else:
                        return "No title"
            except Exception as e:
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
                response = _run.get("response")
                content = response.get("content") if response else None
                return content.split("\n")[0] if content else "No title"
            except Exception as e:
                logger.error(f"Error parsing chat: {e}")
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
                run_parsed = AgentRun.model_validate(_run)
                if run_parsed.message is not None and run_parsed.message.role == "user":
                    content = run_parsed.message.get_content_string()
                    if content:
                        return content
                    else:
                        return "No title"
            except Exception as e:
                logger.error(f"Error parsing chat: {e}")
    return "Unnamed session"
