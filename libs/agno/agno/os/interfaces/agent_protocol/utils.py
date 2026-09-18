"""Utility functions for mapping between Agent Protocol and Agno formats."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from agno.agent import Agent
from agno.agent.remote import RemoteAgent
from agno.run.agent import RunOutput
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


def now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    """Generate a new UUID string."""
    return str(uuid4())


def extract_messages_from_input(input_data: Optional[Dict[str, Any]]) -> Optional[str]:
    """Extract text content from Agent Protocol input format.

    The input format from LangGraph SDK is:
    {"messages": [{"role": "user", "content": "..."}]}
    """
    if not input_data:
        return None

    messages = input_data.get("messages", [])
    if not messages:
        return None

    # Get the last user message content
    for msg in reversed(messages):
        if isinstance(msg, dict):
            content = msg.get("content", "")
            if content:
                return str(content)

    return None


def run_output_to_messages(output: RunOutput) -> List[Dict[str, Any]]:
    """Convert Agno RunOutput to Agent Protocol message format."""
    messages: List[Dict[str, Any]] = []
    if output.content:
        messages.append(
            {
                "type": "ai",
                "content": output.content,
            }
        )
    return messages


def agent_to_ap_info(
    agent: Union[Agent, RemoteAgent],
) -> Dict[str, Any]:
    """Convert an Agno Agent to Agent Protocol agent info dict."""
    agent_id = agent.id or agent.name or new_id()
    return {
        "agent_id": agent_id,
        "name": agent.name or agent_id,
        "description": getattr(agent, "description", None) or "",
        "metadata": {},
        "capabilities": {
            "ap.io.messages": True,
            "ap.io.streaming": True,
        },
    }


def team_to_ap_info(
    team: Union[Team, RemoteTeam],
) -> Dict[str, Any]:
    """Convert an Agno Team to Agent Protocol agent info dict."""
    team_id = team.id or team.name or new_id()
    return {
        "agent_id": team_id,
        "name": team.name or team_id,
        "description": getattr(team, "description", None) or "",
        "metadata": {"type": "team"},
        "capabilities": {
            "ap.io.messages": True,
            "ap.io.streaming": True,
        },
    }


def workflow_to_ap_info(
    workflow: Union[Workflow, RemoteWorkflow],
) -> Dict[str, Any]:
    """Convert an Agno Workflow to Agent Protocol agent info dict."""
    workflow_id = workflow.id or workflow.name or new_id()
    return {
        "agent_id": workflow_id,
        "name": workflow.name or workflow_id,
        "description": getattr(workflow, "description", None) or "",
        "metadata": {"type": "workflow"},
        "capabilities": {
            "ap.io.messages": True,
            "ap.io.streaming": False,
        },
    }
