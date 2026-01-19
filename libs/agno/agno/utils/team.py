from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from agno.agent import Agent
from agno.media import Audio, File, Image, Video
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.utils.log import log_debug
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


def add_interaction_to_team_run_context(
    team_run_context: Dict[str, Any],
    member_name: str,
    task: str,
    run_response: Optional[Union[RunOutput, TeamRunOutput]],
) -> None:
    if "member_responses" not in team_run_context:
        team_run_context["member_responses"] = []
    team_run_context["member_responses"].append(
        {
            "member_name": member_name,
            "task": task,
            "run_response": run_response,
        }
    )
    log_debug(f"Updated team run context with member name: {member_name}")


def get_team_member_interactions_str(team_run_context: Dict[str, Any]) -> str:
    if not team_run_context:
        return ""
    team_member_interactions_str = ""
    if "member_responses" in team_run_context:
        team_member_interactions_str += "<member_interaction_context>\nSee below interactions wit other team members.\n"

        for interaction in team_run_context["member_responses"]:
            response_dict = interaction["run_response"].to_dict()
            response_content = (
                response_dict.get("content")
                or ",".join([tool.get("content", "") for tool in response_dict.get("tools", [])])
                or ""
            )
            team_member_interactions_str += f"Member: {interaction['member_name']}\n"
            team_member_interactions_str += f"Task: {interaction['task']}\n"
            team_member_interactions_str += f"Response: {response_content}\n"
            team_member_interactions_str += "\n"
        team_member_interactions_str += "</member_interaction_context>\n"
    return team_member_interactions_str


def get_team_run_context_images(team_run_context: Dict[str, Any]) -> List[Image]:
    if not team_run_context:
        return []
    images = []
    if "member_responses" in team_run_context:
        for interaction in team_run_context["member_responses"]:
            if interaction["run_response"].images:
                images.extend(interaction["run_response"].images)
    return images


def get_team_run_context_videos(team_run_context: Dict[str, Any]) -> List[Video]:
    if not team_run_context:
        return []
    videos = []
    if "member_responses" in team_run_context:
        for interaction in team_run_context["member_responses"]:
            if interaction["run_response"].videos:
                videos.extend(interaction["run_response"].videos)
    return videos


def get_team_run_context_audio(team_run_context: Dict[str, Any]) -> List[Audio]:
    if not team_run_context:
        return []
    audio = []
    if "member_responses" in team_run_context:
        for interaction in team_run_context["member_responses"]:
            if interaction["run_response"].audio:
                audio.extend(interaction["run_response"].audio)
    return audio


def get_team_run_context_files(team_run_context: Dict[str, Any]) -> List[File]:
    if not team_run_context:
        return []
    files = []
    if "member_responses" in team_run_context:
        for interaction in team_run_context["member_responses"]:
            if interaction["run_response"].files:
                files.extend(interaction["run_response"].files)
    return files
