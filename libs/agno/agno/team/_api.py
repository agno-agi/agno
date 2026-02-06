"""Convenience API methods (print/cli) and cleanup helpers for Team."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agno.team.team import Team

from typing import (
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Set,
    Union,
    cast,
)

from pydantic import BaseModel

from agno.agent import Agent
from agno.filters import FilterExpr
from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.team import (
    TeamRunOutput,
)
from agno.session import TeamSession
from agno.utils.agent import (
    scrub_history_messages_from_run_output,
    scrub_media_from_run_output,
    scrub_tool_results_from_run_output,
)
from agno.utils.log import (
    log_debug,
    log_info,
)
from agno.utils.print_response.team import (
    aprint_response as _util_aprint_response,
)
from agno.utils.print_response.team import (
    aprint_response_stream as _util_aprint_response_stream,
)
from agno.utils.print_response.team import (
    print_response as _util_print_response,
)
from agno.utils.print_response.team import (
    print_response_stream as _util_print_response_stream,
)


def _cleanup_and_store(team: "Team", run_response: TeamRunOutput, session: TeamSession) -> None:
    #  Scrub the stored run based on storage flags
    team._scrub_run_output_for_storage(run_response)

    # Stop the timer for the Run duration
    if run_response.metrics:
        run_response.metrics.stop_timer()

    # Add RunOutput to Agent Session
    session.upsert_run(run_response=run_response)

    # Calculate session metrics
    team._update_session_metrics(session=session, run_response=run_response)

    # Save session to memory
    team.save_session(session=session)


async def _acleanup_and_store(team: "Team", run_response: TeamRunOutput, session: TeamSession) -> None:
    #  Scrub the stored run based on storage flags
    team._scrub_run_output_for_storage(run_response)

    # Stop the timer for the Run duration
    if run_response.metrics:
        run_response.metrics.stop_timer()

    # Add RunOutput to Agent Session
    session.upsert_run(run_response=run_response)

    # Calculate session metrics
    team._update_session_metrics(session=session, run_response=run_response)

    # Save session to memory
    await team.asave_session(session=session)


def print_response(
    team: "Team",
    input: Union[List, Dict, str, Message, BaseModel, List[Message]],
    *,
    stream: Optional[bool] = None,
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    markdown: Optional[bool] = None,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    add_history_to_context: Optional[bool] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    debug_mode: Optional[bool] = None,
    show_message: bool = True,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    show_member_responses: Optional[bool] = None,
    console: Optional[Any] = None,
    tags_to_include_in_markdown: Optional[Set[str]] = None,
    **kwargs: Any,
) -> None:
    if team._has_async_db():
        raise Exception("This method is not supported with an async DB. Please use the async version of this method.")

    if not tags_to_include_in_markdown:
        tags_to_include_in_markdown = {"think", "thinking"}

    if markdown is None:
        markdown = team.markdown

    if team.output_schema is not None:
        markdown = False

    if stream is None:
        stream = team.stream or False

    if "stream_events" in kwargs:
        kwargs.pop("stream_events")

    if show_member_responses is None:
        show_member_responses = team.show_members_responses

    if stream:
        _util_print_response_stream(
            team=cast(Any, team),
            input=input,
            console=console,
            show_message=show_message,
            show_reasoning=show_reasoning,
            show_full_reasoning=show_full_reasoning,
            show_member_responses=show_member_responses,
            tags_to_include_in_markdown=tags_to_include_in_markdown,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            run_id=run_id,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            markdown=markdown,
            stream_events=True,
            knowledge_filters=knowledge_filters,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            metadata=metadata,
            debug_mode=debug_mode,
            **kwargs,
        )
    else:
        _util_print_response(
            team=cast(Any, team),
            input=input,
            console=console,
            show_message=show_message,
            show_reasoning=show_reasoning,
            show_full_reasoning=show_full_reasoning,
            show_member_responses=show_member_responses,
            tags_to_include_in_markdown=tags_to_include_in_markdown,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            run_id=run_id,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            markdown=markdown,
            knowledge_filters=knowledge_filters,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            metadata=metadata,
            debug_mode=debug_mode,
            **kwargs,
        )


async def aprint_response(
    team: "Team",
    input: Union[List, Dict, str, Message, BaseModel, List[Message]],
    *,
    stream: Optional[bool] = None,
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    markdown: Optional[bool] = None,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    add_history_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    metadata: Optional[Dict[str, Any]] = None,
    debug_mode: Optional[bool] = None,
    show_message: bool = True,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    show_member_responses: Optional[bool] = None,
    console: Optional[Any] = None,
    tags_to_include_in_markdown: Optional[Set[str]] = None,
    **kwargs: Any,
) -> None:
    if not tags_to_include_in_markdown:
        tags_to_include_in_markdown = {"think", "thinking"}

    if markdown is None:
        markdown = team.markdown

    if team.output_schema is not None:
        markdown = False

    if stream is None:
        stream = team.stream or False

    if "stream_events" in kwargs:
        kwargs.pop("stream_events")

    if show_member_responses is None:
        show_member_responses = team.show_members_responses

    if stream:
        await _util_aprint_response_stream(
            team=cast(Any, team),
            input=input,
            console=console,
            show_message=show_message,
            show_reasoning=show_reasoning,
            show_full_reasoning=show_full_reasoning,
            show_member_responses=show_member_responses,
            tags_to_include_in_markdown=tags_to_include_in_markdown,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            run_id=run_id,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            markdown=markdown,
            stream_events=True,
            knowledge_filters=knowledge_filters,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            metadata=metadata,
            debug_mode=debug_mode,
            **kwargs,
        )
    else:
        await _util_aprint_response(
            team=cast(Any, team),
            input=input,
            console=console,
            show_message=show_message,
            show_reasoning=show_reasoning,
            show_full_reasoning=show_full_reasoning,
            show_member_responses=show_member_responses,
            tags_to_include_in_markdown=tags_to_include_in_markdown,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            run_id=run_id,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            markdown=markdown,
            knowledge_filters=knowledge_filters,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            metadata=metadata,
            debug_mode=debug_mode,
            **kwargs,
        )


def _get_member_name(team: "Team", entity_id: str) -> str:
    from agno.team.team import Team

    for member in team.members:
        if isinstance(member, Agent):
            if member.id == entity_id:
                return member.name or entity_id
        elif isinstance(member, Team):
            if member.id == entity_id:
                return member.name or entity_id
    return entity_id


def _scrub_run_output_for_storage(team: "Team", run_response: TeamRunOutput) -> bool:
    """
    Scrub run output based on storage flags before persisting to database.
    Returns True if any scrubbing was done, False otherwise.
    """
    scrubbed = False

    if not team.store_media:
        scrub_media_from_run_output(run_response)
        scrubbed = True

    if not team.store_tool_messages:
        scrub_tool_results_from_run_output(run_response)
        scrubbed = True

    if not team.store_history_messages:
        scrub_history_messages_from_run_output(run_response)
        scrubbed = True

    return scrubbed


def _scrub_member_responses(team: "Team", member_responses: List[Union[TeamRunOutput, RunOutput]]) -> None:
    """
    Scrub member responses based on each member's storage flags.
    This is called when saving the team session to ensure member data is scrubbed per member settings.
    Recursively handles nested team's member responses.
    """
    from agno.team.team import Team

    for member_response in member_responses:
        member_id = None
        if isinstance(member_response, RunOutput):
            member_id = member_response.agent_id
        elif isinstance(member_response, TeamRunOutput):
            member_id = member_response.team_id

        if not member_id:
            log_info("Skipping member response with no ID")
            continue

        member_result = team._find_member_by_id(member_id)
        if not member_result:
            log_debug(f"Could not find member with ID: {member_id}")
            continue

        _, member = member_result

        if not member.store_media or not member.store_tool_messages or not member.store_history_messages:
            member._scrub_run_output_for_storage(member_response)  # type: ignore

        # If this is a nested team, recursively scrub its member responses
        if isinstance(member, Team) and isinstance(member_response, TeamRunOutput) and member_response.member_responses:
            member._scrub_member_responses(member_response.member_responses)  # type: ignore


def cli_app(
    team: "Team",
    input: Optional[str] = None,
    user: str = "User",
    emoji: str = ":sunglasses:",
    stream: bool = False,
    markdown: bool = False,
    exit_on: Optional[List[str]] = None,
    **kwargs: Any,
) -> None:
    """Run an interactive command-line interface to interact with the team."""

    from inspect import isawaitable

    from rich.prompt import Prompt

    # Ensuring the team is not using async tools
    if team.tools is not None:
        for tool in team.tools:
            if isawaitable(tool):
                raise NotImplementedError("Use `acli_app` to use async tools.")
            # Alternate method of using isinstance(tool, (MCPTools, MultiMCPTools)) to avoid imports
            if hasattr(type(tool), "__mro__") and any(
                c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__
            ):
                raise NotImplementedError("Use `acli_app` to use MCP tools.")

    if input:
        team.print_response(input=input, stream=stream, markdown=markdown, **kwargs)

    _exit_on = exit_on or ["exit", "quit", "bye"]
    while True:
        user_input = Prompt.ask(f"[bold] {emoji} {user} [/bold]")
        if user_input in _exit_on:
            break

        team.print_response(input=user_input, stream=stream, markdown=markdown, **kwargs)


async def acli_app(
    team: "Team",
    input: Optional[str] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    user: str = "User",
    emoji: str = ":sunglasses:",
    stream: bool = False,
    markdown: bool = False,
    exit_on: Optional[List[str]] = None,
    **kwargs: Any,
) -> None:
    """
    Run an interactive command-line interface to interact with the team.
    Works with team dependencies requiring async logic.
    """
    from rich.prompt import Prompt

    if input:
        await team.aprint_response(
            input=input, stream=stream, markdown=markdown, user_id=user_id, session_id=session_id, **kwargs
        )

    _exit_on = exit_on or ["exit", "quit", "bye"]
    while True:
        message = Prompt.ask(f"[bold] {emoji} {user} [/bold]")
        if message in _exit_on:
            break

        await team.aprint_response(
            input=message, stream=stream, markdown=markdown, user_id=user_id, session_id=session_id, **kwargs
        )


def _update_team_media(team: "Team", run_response: Union[TeamRunOutput, RunOutput]) -> None:
    """Update the team state with the run response."""
    if run_response.images is not None:
        if team.images is None:
            team.images = []
        team.images.extend(run_response.images)
    if run_response.videos is not None:
        if team.videos is None:
            team.videos = []
        team.videos.extend(run_response.videos)
    if run_response.audio is not None:
        if team.audio is None:
            team.audio = []
        team.audio.extend(run_response.audio)
