"""User-facing CLI helpers for Team: response printing and interactive REPL."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Optional,
    Sequence,
    Set,
    Union,
)

from pydantic import BaseModel

if TYPE_CHECKING:
    from agno.team.team import Team

from agno.agent import Agent
from agno.filters import FilterExpr
from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.utils.print_response.team import (
    aprint_response,
    aprint_response_stream,
    print_response,
    print_response_stream,
)


def _get_member_name(team: "Team", entity_id: str) -> str:
    from agno.team.team import Team

    if isinstance(team.members, list):
        for member in team.members:
            if isinstance(member, Agent):
                if member.id == entity_id:
                    return member.name or entity_id
            elif isinstance(member, Team):
                if member.id == entity_id:
                    return member.name or entity_id
    return entity_id


def team_print_response(
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
    from agno.team._init import _has_async_db

    if _has_async_db(team):
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
        print_response_stream(
            team=team,
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
        print_response(
            team=team,
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


async def team_aprint_response(
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
        await aprint_response_stream(
            team=team,
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
        await aprint_response(
            team=team,
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
    if team.tools is not None and isinstance(team.tools, list):
        for tool in team.tools:
            if isawaitable(tool):
                raise NotImplementedError("Use `acli_app` to use async tools.")
            # Alternate method of using isinstance(tool, (MCPTools, MultiMCPTools)) to avoid imports
            if hasattr(type(tool), "__mro__") and any(
                c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__
            ):
                raise NotImplementedError("Use `acli_app` to use MCP tools.")

    if input:
        team_print_response(team, input=input, stream=stream, markdown=markdown, **kwargs)

    _exit_on = exit_on or ["exit", "quit", "bye"]
    while True:
        user_input = Prompt.ask(f"[bold] {emoji} {user} [/bold]")
        if user_input in _exit_on:
            break

        team_print_response(team, input=user_input, stream=stream, markdown=markdown, **kwargs)


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
        await team_aprint_response(
            team, input=input, stream=stream, markdown=markdown, user_id=user_id, session_id=session_id, **kwargs
        )

    _exit_on = exit_on or ["exit", "quit", "bye"]
    while True:
        message = Prompt.ask(f"[bold] {emoji} {user} [/bold]")
        if message in _exit_on:
            break

        await team_aprint_response(
            team, input=message, stream=stream, markdown=markdown, user_id=user_id, session_id=session_id, **kwargs
        )
