from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Union

from agno.agent import Agent
from agno.media import Audio, File, Image, Video
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.utils.log import log_debug
from agno.utils.string import url_safe_string

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


def get_member_id(member: Union[Agent, "Team"]) -> Optional[str]:
    """
    Get the ID of a member

    Priority order:
    1. If the member has an explicitly provided id, use it as-is
    2. If the member has a name, convert that to a URL safe string
    3. Otherwise, return None

    An explicitly provided id is used verbatim (not run through url_safe_string) so that
    it always matches what the team leader is shown in the members prompt and what it
    passes back when delegating tasks. Only a name, which may contain spaces or other
    characters unsafe for tool-call arguments, is converted.
    """
    from agno.team.team import Team

    # First priority: Use the ID if explicitly provided
    if isinstance(member, (Agent, Team)) and member.id is not None:
        return member.id
    # Second priority: Use the name if available
    elif member.name is not None:
        return url_safe_string(member.name)
    else:
        return None


def _member_identity_label(member: Union[Agent, "Team"]) -> str:
    """Describe a member for duplicate-id errors: originals plus the resolved key."""
    member_id = getattr(member, "id", None)
    member_name = getattr(member, "name", None)
    if member_id is not None:
        if member_name:
            return f"id={member_id!r} name={member_name!r}"
        return f"id={member_id!r}"
    if member_name is not None:
        return f"name={member_name!r} (normalized {url_safe_string(member_name)!r})"
    return "<unnamed member>"


def validate_unique_member_ids(
    members: Sequence[Union[Agent, "Team"]],
    *,
    team_id: Optional[str] = None,
    team_name: Optional[str] = None,
) -> None:
    """Reject duplicate resolved ids among a team's direct members.

    Member identity is a namespace-local primary key: ``(team, member_id)``
    must be unique. Resolution uses ``get_member_id`` (explicit id, else
    ``url_safe_string(name)``), so name-fallback collisions such as
    ``Right Team`` / ``right_team`` / ``RightTeam`` fail closed instead of
    first-match. Same id under different parent teams is allowed.

    Members with no resolvable id are skipped: they receive a unique id at
    ``set_id`` time and are not addressable for delegation until then.
    """
    seen: Dict[str, List[str]] = {}
    for member in members:
        resolved_id = get_member_id(member)
        if not resolved_id:
            continue
        seen.setdefault(resolved_id, []).append(_member_identity_label(member))

    collisions = {mid: labels for mid, labels in seen.items() if len(labels) > 1}
    if not collisions:
        return

    team_label = team_name or team_id or "this team"
    collision_parts = [f"{mid!r} <- {'; '.join(labels)}" for mid, labels in collisions.items()]
    raise ValueError(
        f"Duplicate member id(s) among direct members of team {team_label!r}: "
        f"{'; '.join(collision_parts)}. "
        "Member ids are a namespace-local primary key used for delegation and "
        "HITL continue and must be unique within a team. "
        "Assign each member an explicit unique id."
    )


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


def get_team_member_interactions_str(
    team_run_context: Dict[str, Any],
    max_interactions: Optional[int] = None,
) -> str:
    """
    Build a string representation of member interactions from the team run context.

    Args:
        team_run_context: The context containing member responses
        max_interactions: Maximum number of recent interactions to include.
                         None means include all interactions.
                         If set, only the most recent N interactions are included.

    Returns:
        A formatted string with member interactions
    """
    if not team_run_context:
        return ""
    team_member_interactions_str = ""
    if "member_responses" in team_run_context:
        member_responses = team_run_context["member_responses"]

        # If max_interactions is set, only include the most recent N interactions
        if max_interactions is not None and len(member_responses) > max_interactions:
            member_responses = member_responses[-max_interactions:]

        if not member_responses:
            return ""

        team_member_interactions_str += (
            "<member_interaction_context>\nSee below interactions with other team members.\n"
        )

        for interaction in member_responses:
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


def get_team_run_context_images(
    team_run_context: Dict[str, Any],
    max_interactions: Optional[int] = None,
) -> List[Image]:
    if not team_run_context:
        return []
    images = []
    if "member_responses" in team_run_context:
        member_responses = team_run_context["member_responses"]
        if max_interactions is not None and len(member_responses) > max_interactions:
            member_responses = member_responses[-max_interactions:]
        for interaction in member_responses:
            if interaction["run_response"].images:
                images.extend(interaction["run_response"].images)
    return images


def get_team_run_context_videos(
    team_run_context: Dict[str, Any],
    max_interactions: Optional[int] = None,
) -> List[Video]:
    if not team_run_context:
        return []
    videos = []
    if "member_responses" in team_run_context:
        member_responses = team_run_context["member_responses"]
        if max_interactions is not None and len(member_responses) > max_interactions:
            member_responses = member_responses[-max_interactions:]
        for interaction in member_responses:
            if interaction["run_response"].videos:
                videos.extend(interaction["run_response"].videos)
    return videos


def get_team_run_context_audio(
    team_run_context: Dict[str, Any],
    max_interactions: Optional[int] = None,
) -> List[Audio]:
    if not team_run_context:
        return []
    audio = []
    if "member_responses" in team_run_context:
        member_responses = team_run_context["member_responses"]
        if max_interactions is not None and len(member_responses) > max_interactions:
            member_responses = member_responses[-max_interactions:]
        for interaction in member_responses:
            if interaction["run_response"].audio:
                audio.extend(interaction["run_response"].audio)
    return audio


def get_team_run_context_files(
    team_run_context: Dict[str, Any],
    max_interactions: Optional[int] = None,
) -> List[File]:
    if not team_run_context:
        return []
    files = []
    if "member_responses" in team_run_context:
        member_responses = team_run_context["member_responses"]
        if max_interactions is not None and len(member_responses) > max_interactions:
            member_responses = member_responses[-max_interactions:]
        for interaction in member_responses:
            if interaction["run_response"].files:
                files.extend(interaction["run_response"].files)
    return files
