"""User-facing CLI helpers for Agent: response printing and interactive REPL."""

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
    from agno.agent.agent import Agent

from agno.filters import FilterExpr
from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.utils.print_response.agent import (
    aprint_response,
    aprint_response_stream,
    print_response,
    print_response_stream,
)


def agent_print_response(
    agent: Agent,
    input: Union[List, Dict, str, Message, BaseModel, List[Message]],
    *,
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    stream: Optional[bool] = None,
    markdown: Optional[bool] = None,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    add_history_to_context: Optional[bool] = None,
    add_dependencies_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    add_session_state_to_context: Optional[bool] = None,
    metadata: Optional[Dict[str, Any]] = None,
    debug_mode: Optional[bool] = None,
    show_message: bool = True,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    console: Optional[Any] = None,
    tags_to_include_in_markdown: Optional[Set[str]] = None,
    **kwargs: Any,
) -> None:
    from agno.agent import _init

    if _init.has_async_db(agent):
        raise Exception("This method is not supported with an async DB. Please use the async version of this method.")

    if not tags_to_include_in_markdown:
        tags_to_include_in_markdown = {"think", "thinking"}

    if markdown is None:
        markdown = agent.markdown

    if agent.output_schema is not None:
        markdown = False

    # Use stream override value when necessary
    if stream is None:
        stream = False if agent.stream is None else agent.stream

    if "stream_events" in kwargs:
        kwargs.pop("stream_events")

    if stream:
        print_response_stream(
            agent=agent,
            input=input,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            run_id=run_id,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            stream_events=True,
            knowledge_filters=knowledge_filters,
            debug_mode=debug_mode,
            markdown=markdown,
            show_message=show_message,
            show_reasoning=show_reasoning,
            show_full_reasoning=show_full_reasoning,
            tags_to_include_in_markdown=tags_to_include_in_markdown,
            console=console,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            metadata=metadata,
            **kwargs,
        )

    else:
        print_response(
            agent=agent,
            input=input,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            run_id=run_id,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            knowledge_filters=knowledge_filters,
            debug_mode=debug_mode,
            markdown=markdown,
            show_message=show_message,
            show_reasoning=show_reasoning,
            show_full_reasoning=show_full_reasoning,
            tags_to_include_in_markdown=tags_to_include_in_markdown,
            console=console,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            metadata=metadata,
            **kwargs,
        )


async def agent_aprint_response(
    agent: Agent,
    input: Union[List, Dict, str, Message, BaseModel, List[Message]],
    *,
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    stream: Optional[bool] = None,
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
    console: Optional[Any] = None,
    tags_to_include_in_markdown: Optional[Set[str]] = None,
    **kwargs: Any,
) -> None:
    if not tags_to_include_in_markdown:
        tags_to_include_in_markdown = {"think", "thinking"}

    if markdown is None:
        markdown = agent.markdown

    if agent.output_schema is not None:
        markdown = False

    if stream is None:
        stream = agent.stream or False

    if "stream_events" in kwargs:
        kwargs.pop("stream_events")

    if stream:
        await aprint_response_stream(
            agent=agent,
            input=input,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            run_id=run_id,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            stream_events=True,
            knowledge_filters=knowledge_filters,
            debug_mode=debug_mode,
            markdown=markdown,
            show_message=show_message,
            show_reasoning=show_reasoning,
            show_full_reasoning=show_full_reasoning,
            tags_to_include_in_markdown=tags_to_include_in_markdown,
            console=console,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            metadata=metadata,
            **kwargs,
        )
    else:
        await aprint_response(
            agent=agent,
            input=input,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            run_id=run_id,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            knowledge_filters=knowledge_filters,
            debug_mode=debug_mode,
            markdown=markdown,
            show_message=show_message,
            show_reasoning=show_reasoning,
            show_full_reasoning=show_full_reasoning,
            tags_to_include_in_markdown=tags_to_include_in_markdown,
            console=console,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            metadata=metadata,
            **kwargs,
        )


def cli_app(
    agent: Agent,
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
    """Run an interactive command-line interface to interact with the agent."""

    from inspect import isawaitable

    from rich.prompt import Prompt

    # Ensuring the agent is not using our async MCP tools
    if agent.tools is not None and isinstance(agent.tools, list):
        for tool in agent.tools:
            if isawaitable(tool):
                raise NotImplementedError("Use `acli_app` to use async tools.")
            # Alternate method of using isinstance(tool, (MCPTools, MultiMCPTools)) to avoid imports
            if hasattr(type(tool), "__mro__") and any(
                c.__name__ in ["MCPTools", "MultiMCPTools"] for c in type(tool).__mro__
            ):
                raise NotImplementedError("Use `acli_app` to use MCP tools.")

    if input:
        agent_print_response(
            agent,
            input=input,
            stream=stream,
            markdown=markdown,
            user_id=user_id,
            session_id=session_id,
            **kwargs,
        )

    _exit_on = exit_on or ["exit", "quit", "bye"]
    while True:
        message = Prompt.ask(f"[bold] {emoji} {user} [/bold]")
        if message in _exit_on:
            break

        agent_print_response(
            agent,
            input=message,
            stream=stream,
            markdown=markdown,
            user_id=user_id,
            session_id=session_id,
            **kwargs,
        )


async def acli_app(
    agent: Agent,
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
    Run an interactive command-line interface to interact with the agent.
    Works with agent dependencies requiring async logic.
    """
    from rich.prompt import Prompt

    if input:
        await agent_aprint_response(
            agent,
            input=input,
            stream=stream,
            markdown=markdown,
            user_id=user_id,
            session_id=session_id,
            **kwargs,
        )

    _exit_on = exit_on or ["exit", "quit", "bye"]
    while True:
        message = Prompt.ask(f"[bold] {emoji} {user} [/bold]")
        if message in _exit_on:
            break

        await agent_aprint_response(
            agent,
            input=message,
            stream=stream,
            markdown=markdown,
            user_id=user_id,
            session_id=session_id,
            **kwargs,
        )
