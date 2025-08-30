from typing import TYPE_CHECKING, Optional, Union

from agno.agent import Agent
from agno.utils.string import is_valid_uuid, url_safe_string

if TYPE_CHECKING:
    from agno.team.team import Team


def format_member_agent_task(
    task_description: str,
    expected_output: Optional[str] = None,
    team_member_interactions_str: Optional[str] = None,
) -> str:
    member_agent_task = "You are a member of a team of agents. Your goal is to complete the following task:"
    member_agent_task += f"\n\n<task>\n{task_description}\n</task>"

    if expected_output is not None:
        member_agent_task += f"\n\n<expected_output>\n{expected_output}\n</expected_output>"

    if team_member_interactions_str:
        member_agent_task += f"\n\n{team_member_interactions_str}"

    return member_agent_task


def get_member_id(member: Union[Agent, "Team"]) -> str:
    """
    Get the ID of a member

    If the member has an agent_id or team_id, use that if it is not a valid UUID.
    Then if the member has a name, convert that to a URL safe string.
    Then if the member has the default UUID ID, use that.
    Otherwise, return None.
    """
    from agno.team.team import Team

    if isinstance(member, Agent) and member.id is not None and (not is_valid_uuid(member.id)):
        url_safe_member_id = url_safe_string(member.id)
    elif isinstance(member, Team) and member.id is not None and (not is_valid_uuid(member.id)):
        url_safe_member_id = url_safe_string(member.id)
    elif member.name is not None:
        url_safe_member_id = url_safe_string(member.name)
    elif isinstance(member, Agent) and member.id is not None:
        url_safe_member_id = member.id
    elif isinstance(member, Team) and member.id is not None:
        url_safe_member_id = member.id
    else:
        url_safe_member_id = None
    return url_safe_member_id
