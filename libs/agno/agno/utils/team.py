from typing import TYPE_CHECKING, Optional, Union

from agno.agent import Agent
from agno.utils.string import is_valid_uuid, url_safe_string

if TYPE_CHECKING:
    from agno.team.team import Team


def format_member_agent_task(
    task_description: str,
    team_member_interactions_str: Optional[str] = None,
    team_history_str: Optional[str] = None,
) -> str:
    member_task_str = ""

    if team_member_interactions_str:
        member_task_str += f"{team_member_interactions_str}\n\n"

    if team_history_str:
        member_task_str += f"{team_history_str}\n\n"

    member_task_str += f"{task_description}"

    return member_task_str


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
