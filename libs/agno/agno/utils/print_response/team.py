import json
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Set, Union, get_args

from pydantic import BaseModel

from agno.filters import FilterExpr
from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.reasoning.step import ReasoningStep
from agno.run.agent import RunEvent as AgentRunEvent
from agno.run.agent import RunOutput
from agno.run.base import BaseRunOutputEvent
from agno.run.team import TeamRunEvent, TeamRunOutput, TeamRunOutputEvent
from agno.utils.log import log_warning
from agno.utils.message import get_text_from_message
from agno.utils.response import build_reasoning_step_panel, create_panel, escape_markdown_tags, format_tool_calls
from agno.utils.timer import Timer

if TYPE_CHECKING:
    from agno.team.team import Team


def print_response(
    team: "Team",
    input: Union[List, Dict, str, Message, BaseModel, List[Message]],
    console: Optional[Any] = None,
    show_message: bool = True,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    show_member_responses: Optional[bool] = None,
    tags_to_include_in_markdown: Optional[Set[str]] = None,
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    markdown: bool = False,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    add_history_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    metadata: Optional[Dict[str, Any]] = None,
    debug_mode: Optional[bool] = None,
    **kwargs: Any,
) -> None:
    import textwrap

    from rich.console import Group
    from rich.json import JSON
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.status import Status
    from rich.text import Text

    from agno.utils.response import format_tool_calls

    if not tags_to_include_in_markdown:
        tags_to_include_in_markdown = {"think", "thinking"}

    with Live(console=console) as live_console:
        status = Status("Working...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
        live_console.update(status)

        response_timer = Timer()
        response_timer.start()
        # Panels to be rendered
        panels = [status]
        # First render the message panel if the message is not None
        if input and show_message:
            # Convert message to a panel
            message_content = get_text_from_message(input)
            message_panel = create_panel(
                content=Text(message_content, style="green"),
                title="Message",
                border_style="cyan",
            )
            panels.append(message_panel)
            live_console.update(Group(*panels))

        # Run the agent
        run_response: TeamRunOutput = team.run(  # type: ignore
            input=input,
            run_id=run_id,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            stream=False,
            stream_events=True,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            knowledge_filters=knowledge_filters,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            metadata=metadata,
            debug_mode=debug_mode,
            **kwargs,
        )
        response_timer.stop()

        if run_response.input is not None and run_response.input.input_content != input:
            # Input was modified during the run
            panels = [status]
            if show_message:
                # Convert message to a panel
                message_content = get_text_from_message(run_response.input.input_content)
                message_panel = create_panel(
                    content=Text(message_content, style="green"),
                    title="Message",
                    border_style="cyan",
                )
                panels.append(message_panel)  # type: ignore
                live_console.update(Group(*panels))

        team_markdown = False
        member_markdown = {}
        if markdown:
            if isinstance(team.members, list):
                for member in team.members:
                    if member.id is not None:
                        member_markdown[member.id] = True
            team_markdown = True

        if team.output_schema is not None:
            team_markdown = False

        if isinstance(team.members, list):
            for member in team.members:
                if member.output_schema is not None and member.id is not None:
                    member_markdown[member.id] = False  # type: ignore

        # Handle reasoning
        reasoning_steps = []
        if isinstance(run_response, TeamRunOutput) and run_response.reasoning_steps is not None:
            reasoning_steps = run_response.reasoning_steps

        if len(reasoning_steps) > 0 and show_reasoning:
            # Create panels for reasoning steps
            for i, step in enumerate(reasoning_steps, 1):
                reasoning_panel = build_reasoning_step_panel(i, step, show_full_reasoning)
                panels.append(reasoning_panel)
            live_console.update(Group(*panels))

        if isinstance(run_response, TeamRunOutput) and run_response.reasoning_content is not None and show_reasoning:
            # Create panel for thinking
            thinking_panel = create_panel(
                content=Text(run_response.reasoning_content),
                title=f"Thinking ({response_timer.elapsed:.1f}s)",
                border_style="green",
            )
            panels.append(thinking_panel)
            live_console.update(Group(*panels))

        if isinstance(run_response, TeamRunOutput):
            # Add team level tool calls panel before member responses
            if run_response.tools:
                formatted_calls = format_tool_calls(run_response.tools)
                if formatted_calls:
                    console_width = console.width if console else 80
                    # Allow for panel borders and padding
                    panel_width = console_width + 30

                    lines = []
                    for call in formatted_calls:
                        wrapped_call = textwrap.fill(
                            f"• {call}", width=panel_width, subsequent_indent="  "
                        )  # Indent continuation lines
                        lines.append(wrapped_call)

                    # Join with blank lines between items
                    tool_calls_text = "\n\n".join(lines)

                    # Add compression stats at end of tool calls
                    if team.compression_manager is not None and team.compression_manager.stats:
                        stats = team.compression_manager.stats
                        saved = stats.get("original_size", 0) - stats.get("compressed_size", 0)
                        orig = stats.get("original_size", 1)
                        if stats.get("tool_results_compressed", 0) > 0:
                            tool_calls_text += f"\n\ncompressed: {stats.get('tool_results_compressed', 0)} | Saved: {saved:,} chars ({saved / orig * 100:.0f}%)"
                        team.compression_manager.stats.clear()

                    team_tool_calls_panel = create_panel(
                        content=tool_calls_text,
                        title="Team Tool Calls",
                        border_style="yellow",
                    )
                    panels.append(team_tool_calls_panel)
                    live_console.update(Group(*panels))

            response_content_batch: Union[str, JSON, Markdown] = _parse_response_content(  # type: ignore
                run_response, tags_to_include_in_markdown, show_markdown=team_markdown
            )

            # Create panel for response
            response_panel = create_panel(
                content=response_content_batch,
                title=f"Response ({response_timer.elapsed:.1f}s)",
                border_style="blue",
            )
            panels.append(response_panel)

            # Add citations
            if run_response.citations is not None and run_response.citations.urls is not None:
                md_lines = []

                # Add search queries if present
                if run_response.citations.search_queries:
                    md_lines.append("**Search Queries:**")
                    for query in run_response.citations.search_queries:
                        md_lines.append(f"- {query}")
                    md_lines.append("")  # Empty line before URLs

                # Add URL citations
                md_lines.extend(
                    f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                    for i, citation in enumerate(run_response.citations.urls)
                    if citation.url  # Only include citations with valid URLs
                )

                md_content = "\n".join(md_lines)
                if md_content:  # Only create panel if there are citations
                    citations_panel = create_panel(
                        content=Markdown(md_content),
                        title="Citations",
                        border_style="green",
                    )
                    panels.append(citations_panel)

            if team.memory_manager is not None:
                if team.memory_manager.memories_updated:
                    memory_panel = create_panel(
                        content=Text("Memories updated"),
                        title="Memories",
                        border_style="green",
                    )
                    panels.append(memory_panel)

            if team.session_summary_manager is not None and team.session_summary_manager.summaries_updated:
                summary_panel = create_panel(
                    content=Text("Session summary updated"),
                    title="Session Summary",
                    border_style="green",
                )
                panels.append(summary_panel)
                team.session_summary_manager.summaries_updated = False

        # Final update to remove the "Working..." status
        panels = [p for p in panels if not isinstance(p, Status)]
        live_console.update(Group(*panels))


def print_response_stream(
    team: "Team",
    input: Union[List, Dict, str, Message, BaseModel, List[Message]],
    console: Optional[Any] = None,
    show_message: bool = True,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    show_member_responses: Optional[bool] = None,
    tags_to_include_in_markdown: Optional[Set[str]] = None,
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    markdown: bool = False,
    stream_events: bool = False,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    add_history_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    metadata: Optional[Dict[str, Any]] = None,
    debug_mode: Optional[bool] = None,
    **kwargs: Any,
) -> None:
    import textwrap

    from rich.console import Group
    from rich.json import JSON
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.status import Status
    from rich.text import Text

    from agno.utils.response import format_tool_calls

    if not tags_to_include_in_markdown:
        tags_to_include_in_markdown = {"think", "thinking"}

    stream_events = True  # With streaming print response, we need to stream intermediate steps

    _response_content: str = ""
    _response_reasoning_content: str = ""
    reasoning_steps: List[ReasoningStep] = []

    # Track tool calls by member and team
    member_tool_calls = {}  # type: ignore
    team_tool_calls = []  # type: ignore

    # Track processed tool calls to avoid duplicates
    processed_tool_calls = set()

    # Track streaming member content and names
    member_streaming_content: Dict[str, str] = {}
    member_names: Dict[str, str] = {}
    # Track order of member appearance
    member_order: List[str] = []

    with Live(console=console) as live_console:
        status = Status("Working...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
        live_console.update(status)
        response_timer = Timer()
        response_timer.start()
        # Flag which indicates if the panels should be rendered
        render = False
        # Panels to be rendered
        panels = [status]
        # First render the message panel if the message is not None
        if input and show_message:
            render = True
            # Convert message to a panel
            message_content = get_text_from_message(input)
            message_panel = create_panel(
                content=Text(message_content, style="green"),
                title="Message",
                border_style="cyan",
            )
            panels.append(message_panel)
        if render:
            live_console.update(Group(*panels))

        # Get response from the team
        stream_resp = team.run(  # type: ignore
            input=input,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            stream=True,
            stream_events=stream_events,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            run_id=run_id,
            knowledge_filters=knowledge_filters,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            metadata=metadata,
            debug_mode=debug_mode,
            yield_run_output=True,
            **kwargs,
        )

        input_content = get_text_from_message(input)

        team_markdown = None
        member_markdown = {}

        final_run_response = None
        for resp in stream_resp:
            if team_markdown is None:
                if markdown:
                    team_markdown = True
                else:
                    team_markdown = False

                if team.output_schema is not None:
                    team_markdown = False

            if isinstance(resp, TeamRunOutput):
                final_run_response = resp
                continue

            if isinstance(resp, tuple(get_args(TeamRunOutputEvent))):
                if resp.event == TeamRunEvent.run_content:
                    if isinstance(resp.content, str):
                        _response_content += resp.content
                    elif team.output_schema is not None and isinstance(resp.content, BaseModel):
                        try:
                            _response_content = JSON(resp.content.model_dump_json(exclude_none=True), indent=2)  # type: ignore
                        except Exception as e:
                            log_warning(f"Failed to convert response to JSON: {e}")
                    elif team.output_schema is not None and isinstance(resp.content, dict):
                        try:
                            _response_content = JSON(json.dumps(resp.content), indent=2)  # type: ignore
                        except Exception as e:
                            log_warning(f"Failed to convert response to JSON: {e}")
                    if hasattr(resp, "reasoning_content") and resp.reasoning_content is not None:  # type: ignore
                        _response_reasoning_content += resp.reasoning_content  # type: ignore
                if hasattr(resp, "reasoning_steps") and resp.reasoning_steps is not None:  # type: ignore
                    reasoning_steps = resp.reasoning_steps  # type: ignore

                if resp.event == TeamRunEvent.pre_hook_completed:  # type: ignore
                    if resp.run_input is not None:  # type: ignore
                        input_content = get_text_from_message(resp.run_input.input_content)  # type: ignore

                # Collect team tool calls when they START so the panel appears before member responses
                if resp.event == TeamRunEvent.tool_call_started and resp.tool:  # type: ignore
                    tool = resp.tool  # type: ignore
                    if tool.tool_call_id:
                        tool_id = tool.tool_call_id
                    else:
                        tool_id = str(hash(str(tool)))
                    if tool_id not in processed_tool_calls:
                        processed_tool_calls.add(tool_id)
                        team_tool_calls.append(tool)

                # Update team tool calls when they COMPLETE (replaces the started entry)
                if resp.event == TeamRunEvent.tool_call_completed and resp.tool:  # type: ignore
                    tool = resp.tool  # type: ignore
                    if tool.tool_call_id:
                        tool_id = tool.tool_call_id
                    else:
                        tool_id = str(hash(str(tool)))
                    if tool_id not in processed_tool_calls:
                        processed_tool_calls.add(tool_id)
                        team_tool_calls.append(tool)
                    else:
                        # Update the existing tool call with the completed version
                        for i, existing_tool in enumerate(team_tool_calls):
                            existing_id = (
                                existing_tool.tool_call_id
                                if existing_tool.tool_call_id
                                else str(hash(str(existing_tool)))
                            )
                            if existing_id == tool_id:
                                team_tool_calls[i] = tool
                                break

            # Handle agent member events (these have agent_id/agent_name, not team_id/team_name)
            if (
                show_member_responses
                and isinstance(resp, BaseRunOutputEvent)
                and hasattr(resp, "agent_id")
                and resp.agent_id
            ):
                agent_id = resp.agent_id
                if agent_id not in member_names:
                    member_names[agent_id] = team._get_member_name(agent_id) or getattr(
                        resp, "agent_name", "Team Member"
                    )
                if agent_id not in member_order:
                    member_order.append(agent_id)

                # Accumulate streaming content from member agents
                if resp.event == AgentRunEvent.run_content.value:
                    if isinstance(resp.content, str):
                        if agent_id not in member_streaming_content:
                            member_streaming_content[agent_id] = ""
                        member_streaming_content[agent_id] += resp.content

                # Track member tool calls
                if resp.event == AgentRunEvent.tool_call_started.value and hasattr(resp, "tool") and resp.tool:
                    tool = resp.tool
                    if tool.tool_call_id:
                        tool_id = tool.tool_call_id
                    else:
                        tool_id = str(hash(str(tool)))
                    if agent_id not in member_tool_calls:
                        member_tool_calls[agent_id] = []
                    if tool_id not in processed_tool_calls:
                        processed_tool_calls.add(tool_id)
                        member_tool_calls[agent_id].append(tool)

                if resp.event == AgentRunEvent.tool_call_completed.value and hasattr(resp, "tool") and resp.tool:
                    tool = resp.tool
                    if tool.tool_call_id:
                        tool_id = tool.tool_call_id
                    else:
                        tool_id = str(hash(str(tool)))
                    if agent_id not in member_tool_calls:
                        member_tool_calls[agent_id] = []
                    if tool_id not in processed_tool_calls:
                        processed_tool_calls.add(tool_id)
                        member_tool_calls[agent_id].append(tool)
                    else:
                        # Update existing tool call with completed version
                        for i, existing_tool in enumerate(member_tool_calls[agent_id]):
                            existing_id = (
                                existing_tool.tool_call_id
                                if existing_tool.tool_call_id
                                else str(hash(str(existing_tool)))
                            )
                            if existing_id == tool_id:
                                member_tool_calls[agent_id][i] = tool
                                break

            response_content_stream: Union[str, Markdown] = _response_content
            # Escape special tags before markdown conversion
            if team_markdown:
                escaped_content = escape_markdown_tags(_response_content, tags_to_include_in_markdown)
                response_content_stream = Markdown(escaped_content)

            # Create new panels for each chunk
            panels = []

            # Show status spinner above everything while waiting for response content
            if not _response_content:
                panels.append(status)

            if input_content and show_message:
                render = True
                # Convert message to a panel
                message_panel = create_panel(
                    content=Text(input_content, style="green"),
                    title="Message",
                    border_style="cyan",
                )
                panels.append(message_panel)

            if len(reasoning_steps) > 0 and show_reasoning:
                render = True
                # Create panels for reasoning steps
                for i, step in enumerate(reasoning_steps, 1):
                    reasoning_panel = build_reasoning_step_panel(i, step, show_full_reasoning)
                    panels.append(reasoning_panel)

            if len(_response_reasoning_content) > 0 and show_reasoning:
                render = True
                # Create panel for thinking
                thinking_panel = create_panel(
                    content=Text(_response_reasoning_content),
                    title=f"Thinking ({response_timer.elapsed:.1f}s)",
                    border_style="green",
                )
                panels.append(thinking_panel)

            # Render streaming member panels (tool calls + response, grouped per member)
            if show_member_responses:
                for mid in member_order:
                    m_name = member_names.get(mid, "Team Member")

                    # Show member tool calls if any
                    if mid in member_tool_calls and member_tool_calls[mid]:
                        formatted_calls = format_tool_calls(member_tool_calls[mid])
                        if formatted_calls:
                            console_width = console.width if console else 80
                            panel_width = console_width + 30

                            lines = []
                            for call in formatted_calls:
                                wrapped_call = textwrap.fill(f"• {call}", width=panel_width, subsequent_indent="  ")
                                lines.append(wrapped_call)

                            tool_calls_text = "\n\n".join(lines)

                            member_tool_calls_panel = create_panel(
                                content=tool_calls_text,
                                title=f"{m_name} Tool Calls",
                                border_style="yellow",
                            )
                            panels.append(member_tool_calls_panel)

                    # Show member response content if any
                    if mid in member_streaming_content and member_streaming_content[mid]:
                        m_content: Union[str, Markdown] = member_streaming_content[mid]
                        if markdown:
                            m_content = Markdown(
                                escape_markdown_tags(member_streaming_content[mid], tags_to_include_in_markdown)
                            )

                        member_response_panel = create_panel(
                            content=m_content,
                            title=f"{m_name} Response",
                            border_style="magenta",
                        )
                        panels.append(member_response_panel)

            # Add team tool calls panel after member responses
            if team_tool_calls:
                formatted_calls = format_tool_calls(team_tool_calls)
                if formatted_calls:
                    console_width = console.width if console else 80
                    panel_width = console_width + 30

                    lines = []
                    # Create a set to track already added calls by their string representation
                    added_calls = set()
                    for call in formatted_calls:
                        if call not in added_calls:
                            added_calls.add(call)
                            # Wrap the call text to fit within the panel
                            wrapped_call = textwrap.fill(f"• {call}", width=panel_width, subsequent_indent="  ")
                            lines.append(wrapped_call)

                    # Join with blank lines between items
                    tool_calls_text = "\n\n".join(lines)

                    # Add compression stats if available (don't clear - will be cleared in final_panels)
                    if team.compression_manager is not None and team.compression_manager.stats:
                        stats = team.compression_manager.stats
                        saved = stats.get("original_size", 0) - stats.get("compressed_size", 0)
                        orig = stats.get("original_size", 1)
                        if stats.get("tool_results_compressed", 0) > 0:
                            tool_calls_text += f"\n\ncompressed: {stats.get('tool_results_compressed', 0)} | Saved: {saved:,} chars ({saved / orig * 100:.0f}%)"

                    team_tool_calls_panel = create_panel(
                        content=tool_calls_text,
                        title="Team Tool Calls",
                        border_style="yellow",
                    )
                    panels.append(team_tool_calls_panel)

            # Add the team response panel at the end (only if there's actual content)
            if _response_content:
                render = True
                # Create panel for response
                response_panel = create_panel(
                    content=response_content_stream,
                    title=f"Response ({response_timer.elapsed:.1f}s)",
                    border_style="blue",
                )
                panels.append(response_panel)

            if render or len(panels) > 0:
                live_console.update(Group(*panels))

        response_timer.stop()
        run_response = final_run_response

        # Add citations
        if hasattr(resp, "citations") and resp.citations is not None and resp.citations.urls is not None:
            md_lines = []

            # Add search queries if present
            if resp.citations.search_queries:
                md_lines.append("**Search Queries:**")
                for query in resp.citations.search_queries:
                    md_lines.append(f"- {query}")
                md_lines.append("")  # Empty line before URLs

            # Add URL citations
            md_lines.extend(
                f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                for i, citation in enumerate(resp.citations.urls)
                if citation.url  # Only include citations with valid URLs
            )

            md_content = "\n".join(md_lines)
            if md_content:  # Only create panel if there are citations
                citations_panel = create_panel(
                    content=Markdown(md_content),
                    title="Citations",
                    border_style="green",
                )
                panels.append(citations_panel)
                live_console.update(Group(*panels))

        if team.memory_manager is not None:
            if team.memory_manager.memories_updated:
                memory_panel = create_panel(
                    content=Text("Memories updated"),
                    title="Memories",
                    border_style="green",
                )
                panels.append(memory_panel)
                live_console.update(Group(*panels))

        if team.session_summary_manager is not None and team.session_summary_manager.summaries_updated:
            summary_panel = create_panel(
                content=Text("Session summary updated"),
                title="Session Summary",
                border_style="green",
            )
            panels.append(summary_panel)
            live_console.update(Group(*panels))
            team.session_summary_manager.summaries_updated = False

        # Final update to remove the "Working..." status
        panels = [p for p in panels if not isinstance(p, Status)]

        if markdown:
            if isinstance(team.members, list):
                for member in team.members:
                    if member.id is not None:
                        member_markdown[member.id] = True

        if isinstance(team.members, list):
            for member in team.members:
                if member.output_schema is not None and member.id is not None:
                    member_markdown[member.id] = False  # type: ignore

        # Final panels assembly - we'll recreate the panels from scratch to ensure correct order
        final_panels = []

        # Start with the message
        if input_content and show_message:
            message_panel = create_panel(
                content=Text(input_content, style="green"),
                title="Message",
                border_style="cyan",
            )
            final_panels.append(message_panel)

        # Add reasoning steps
        if reasoning_steps and show_reasoning:
            for i, step in enumerate(reasoning_steps, 1):
                reasoning_panel = build_reasoning_step_panel(i, step, show_full_reasoning)
                final_panels.append(reasoning_panel)

        # Add thinking panel if available
        if _response_reasoning_content and show_reasoning:
            thinking_panel = create_panel(
                content=Text(_response_reasoning_content),
                title=f"Thinking ({response_timer.elapsed:.1f}s)",
                border_style="green",
            )
            final_panels.append(thinking_panel)

        # Add member tool calls and responses (grouped per member)
        if show_member_responses and final_run_response is not None and hasattr(final_run_response, "member_responses"):
            for member_response in final_run_response.member_responses:
                member_id = None
                if isinstance(member_response, RunOutput) and member_response.agent_id is not None:
                    member_id = member_response.agent_id
                elif isinstance(member_response, TeamRunOutput) and member_response.team_id is not None:
                    member_id = member_response.team_id

                if member_id:
                    m_name = team._get_member_name(member_id)

                    # Add tool calls if any
                    if member_id in member_tool_calls and member_tool_calls[member_id]:
                        formatted_calls = format_tool_calls(member_tool_calls[member_id])
                        if formatted_calls:
                            console_width = console.width if console else 80
                            panel_width = console_width + 30

                            lines = []
                            added_calls = set()
                            for call in formatted_calls:
                                if call not in added_calls:
                                    added_calls.add(call)
                                    wrapped_call = textwrap.fill(f"• {call}", width=panel_width, subsequent_indent="  ")
                                    lines.append(wrapped_call)

                            tool_calls_text = "\n\n".join(lines)

                            member_tool_calls_panel = create_panel(
                                content=tool_calls_text,
                                title=f"{m_name} Tool Calls",
                                border_style="yellow",
                            )
                            final_panels.append(member_tool_calls_panel)

                    # Add response
                    show_md = member_markdown.get(member_id, False)

                    member_response_content = _parse_response_content(
                        member_response,
                        tags_to_include_in_markdown,
                        show_markdown=show_md,
                    )

                    member_response_panel = create_panel(
                        content=member_response_content,
                        title=f"{m_name} Response",
                        border_style="magenta",
                    )
                    final_panels.append(member_response_panel)

                    # Add member citations if any
                    if member_response.citations is not None and member_response.citations.urls is not None:
                        md_lines = []
                        if member_response.citations.search_queries:
                            md_lines.append("**Search Queries:**")
                            for query in member_response.citations.search_queries:
                                md_lines.append(f"- {query}")
                            md_lines.append("")
                        md_lines.extend(
                            f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                            for i, citation in enumerate(member_response.citations.urls)
                            if citation.url
                        )
                        md_content = "\n".join(md_lines)
                        if md_content:
                            citations_panel = create_panel(
                                content=Markdown(md_content),
                                title="Citations",
                                border_style="magenta",
                            )
                            final_panels.append(citations_panel)

        # Add team tool calls after member responses
        if team_tool_calls:
            formatted_calls = format_tool_calls(team_tool_calls)
            if formatted_calls:
                console_width = console.width if console else 80
                panel_width = console_width + 30

                lines = []
                # Create a set to track already added calls by their string representation
                added_calls = set()
                for call in formatted_calls:
                    if call not in added_calls:
                        added_calls.add(call)
                        # Wrap the call text to fit within the panel
                        wrapped_call = textwrap.fill(f"• {call}", width=panel_width, subsequent_indent="  ")
                        lines.append(wrapped_call)

                tool_calls_text = "\n\n".join(lines)

                # Add compression stats at end of tool calls
                if team.compression_manager is not None and team.compression_manager.stats:
                    stats = team.compression_manager.stats
                    saved = stats.get("original_size", 0) - stats.get("compressed_size", 0)
                    orig = stats.get("original_size", 1)
                    if stats.get("tool_results_compressed", 0) > 0:
                        tool_calls_text += f"\n\ncompressed: {stats.get('tool_results_compressed', 0)} | Saved: {saved:,} chars ({saved / orig * 100:.0f}%)"
                    team.compression_manager.stats.clear()

                team_tool_calls_panel = create_panel(
                    content=tool_calls_text,
                    title="Team Tool Calls",
                    border_style="yellow",
                )
                final_panels.append(team_tool_calls_panel)

        # Add team response
        if _response_content:
            response_content_stream = _response_content
            if team_markdown:
                escaped_content = escape_markdown_tags(_response_content, tags_to_include_in_markdown)
                response_content_stream = Markdown(escaped_content)

            response_panel = create_panel(
                content=response_content_stream,
                title=f"Response ({response_timer.elapsed:.1f}s)",
                border_style="blue",
            )
            final_panels.append(response_panel)

        # Add team citations
        if hasattr(resp, "citations") and resp.citations is not None and resp.citations.urls is not None:
            md_lines = []

            # Add search queries if present
            if resp.citations.search_queries:
                md_lines.append("**Search Queries:**")
                for query in resp.citations.search_queries:
                    md_lines.append(f"- {query}")
                md_lines.append("")  # Empty line before URLs

            # Add URL citations
            md_lines.extend(
                f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                for i, citation in enumerate(resp.citations.urls)
                if citation.url  # Only include citations with valid URLs
            )

            md_content = "\n".join(md_lines)
            if md_content:  # Only create panel if there are citations
                citations_panel = create_panel(
                    content=Markdown(md_content),
                    title="Citations",
                    border_style="green",
                )
                final_panels.append(citations_panel)

        # Final update with correctly ordered panels
        live_console.update(Group(*final_panels))


async def aprint_response(
    team: "Team",
    input: Union[List, Dict, str, Message, BaseModel, List[Message]],
    console: Optional[Any] = None,
    show_message: bool = True,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    show_member_responses: Optional[bool] = None,
    tags_to_include_in_markdown: Optional[Set[str]] = None,
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    markdown: bool = False,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    add_history_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    metadata: Optional[Dict[str, Any]] = None,
    debug_mode: Optional[bool] = None,
    **kwargs: Any,
) -> None:
    import textwrap

    from rich.console import Group
    from rich.json import JSON
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.status import Status
    from rich.text import Text

    from agno.utils.response import format_tool_calls

    if not tags_to_include_in_markdown:
        tags_to_include_in_markdown = {"think", "thinking"}

    with Live(console=console) as live_console:
        status = Status("Working...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
        live_console.update(status)

        response_timer = Timer()
        response_timer.start()
        # Panels to be rendered
        panels = [status]
        # First render the message panel if the message is not None
        if input and show_message:
            # Convert message to a panel
            message_content = get_text_from_message(input)
            message_panel = create_panel(
                content=Text(message_content, style="green"),
                title="Message",
                border_style="cyan",
            )
            panels.append(message_panel)
            live_console.update(Group(*panels))

        # Run the agent
        run_response: TeamRunOutput = await team.arun(  # type: ignore
            input=input,
            run_id=run_id,
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            stream=False,
            stream_events=True,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            knowledge_filters=knowledge_filters,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            metadata=metadata,
            debug_mode=debug_mode,
            **kwargs,
        )
        response_timer.stop()

        if run_response.input is not None and run_response.input.input_content != input:
            # Input was modified during the run
            panels = [status]
            if show_message:
                # Convert message to a panel
                message_content = get_text_from_message(run_response.input.input_content)
                message_panel = create_panel(
                    content=Text(message_content, style="green"),
                    title="Message",
                    border_style="cyan",
                )
                panels.append(message_panel)  # type: ignore
                live_console.update(Group(*panels))

        team_markdown = False
        member_markdown = {}
        if markdown:
            if isinstance(team.members, list):
                for member in team.members:
                    if member.id is not None:
                        member_markdown[member.id] = True
            team_markdown = True

        if team.output_schema is not None:
            team_markdown = False

        if isinstance(team.members, list):
            for member in team.members:
                if member.output_schema is not None and member.id is not None:
                    member_markdown[member.id] = False  # type: ignore

        # Handle reasoning
        reasoning_steps = []
        if isinstance(run_response, TeamRunOutput) and run_response.reasoning_steps is not None:
            reasoning_steps = run_response.reasoning_steps

        if len(reasoning_steps) > 0 and show_reasoning:
            # Create panels for reasoning steps
            for i, step in enumerate(reasoning_steps, 1):
                reasoning_panel = build_reasoning_step_panel(i, step, show_full_reasoning)
                panels.append(reasoning_panel)
            live_console.update(Group(*panels))

        if isinstance(run_response, TeamRunOutput) and run_response.reasoning_content is not None and show_reasoning:
            # Create panel for thinking
            thinking_panel = create_panel(
                content=Text(run_response.reasoning_content),
                title=f"Thinking ({response_timer.elapsed:.1f}s)",
                border_style="green",
            )
            panels.append(thinking_panel)
            live_console.update(Group(*panels))

        if isinstance(run_response, TeamRunOutput):
            # Add team level tool calls panel before member responses
            if run_response.tools:
                formatted_calls = format_tool_calls(run_response.tools)
                if formatted_calls:
                    console_width = console.width if console else 80
                    # Allow for panel borders and padding
                    panel_width = console_width + 30

                    lines = []
                    for call in formatted_calls:
                        # Wrap the call text to fit within the panel
                        wrapped_call = textwrap.fill(f"• {call}", width=panel_width, subsequent_indent="  ")
                        lines.append(wrapped_call)

                    tool_calls_text = "\n\n".join(lines)

                    # Add compression stats at end of tool calls
                    if team.compression_manager is not None and team.compression_manager.stats:
                        stats = team.compression_manager.stats
                        saved = stats.get("original_size", 0) - stats.get("compressed_size", 0)
                        orig = stats.get("original_size", 1)
                        if stats.get("tool_results_compressed", 0) > 0:
                            tool_calls_text += f"\n\ncompressed: {stats.get('tool_results_compressed', 0)} | Saved: {saved:,} chars ({saved / orig * 100:.0f}%)"
                        team.compression_manager.stats.clear()

                    team_tool_calls_panel = create_panel(
                        content=tool_calls_text,
                        title="Team Tool Calls",
                        border_style="yellow",
                    )
                    panels.append(team_tool_calls_panel)
                    live_console.update(Group(*panels))

            # Handle member responses
            if show_member_responses:
                for member_response in run_response.member_responses:
                    # Handle member reasoning
                    reasoning_steps = []
                    if isinstance(member_response, RunOutput) and member_response.reasoning_steps is not None:
                        reasoning_steps.extend(member_response.reasoning_steps)

                    if len(reasoning_steps) > 0 and show_reasoning:
                        # Create panels for reasoning steps
                        for i, step in enumerate(reasoning_steps, 1):
                            member_reasoning_panel = build_reasoning_step_panel(
                                i, step, show_full_reasoning, color="magenta"
                            )
                            panels.append(member_reasoning_panel)

                    # Add tool calls panel for member if available
                    if hasattr(member_response, "tools") and member_response.tools:
                        member_name = None
                        if isinstance(member_response, RunOutput) and member_response.agent_id is not None:
                            member_name = team._get_member_name(member_response.agent_id)
                        elif isinstance(member_response, TeamRunOutput) and member_response.team_id is not None:
                            member_name = team._get_member_name(member_response.team_id)

                        if member_name:
                            # Format tool calls
                            formatted_calls = format_tool_calls(member_response.tools)
                            if formatted_calls:
                                console_width = console.width if console else 80
                                panel_width = console_width + 30

                                lines = []
                                for call in formatted_calls:
                                    wrapped_call = textwrap.fill(f"• {call}", width=panel_width, subsequent_indent="  ")
                                    lines.append(wrapped_call)

                                tool_calls_text = "\n\n".join(lines)

                                member_tool_calls_panel = create_panel(
                                    content=tool_calls_text,
                                    title=f"{member_name} Tool Calls",
                                    border_style="yellow",
                                )
                                panels.append(member_tool_calls_panel)
                                live_console.update(Group(*panels))

                    show_markdown = False
                    if isinstance(member_response, RunOutput) and member_response.agent_id is not None:
                        show_markdown = member_markdown.get(member_response.agent_id, False)
                    elif isinstance(member_response, TeamRunOutput) and member_response.team_id is not None:
                        show_markdown = member_markdown.get(member_response.team_id, False)

                    member_response_content: Union[str, JSON, Markdown] = _parse_response_content(  # type: ignore
                        member_response,
                        tags_to_include_in_markdown,
                        show_markdown=show_markdown,
                    )

                    # Create panel for member response
                    if isinstance(member_response, RunOutput) and member_response.agent_id is not None:
                        member_response_panel = create_panel(
                            content=member_response_content,
                            title=f"{team._get_member_name(member_response.agent_id)} Response",
                            border_style="magenta",
                        )
                    elif isinstance(member_response, TeamRunOutput) and member_response.team_id is not None:
                        member_response_panel = create_panel(
                            content=member_response_content,
                            title=f"{team._get_member_name(member_response.team_id)} Response",
                            border_style="magenta",
                        )
                    panels.append(member_response_panel)

                    if member_response.citations is not None and member_response.citations.urls is not None:
                        md_lines = []

                        # Add search queries if present
                        if member_response.citations.search_queries:
                            md_lines.append("**Search Queries:**")
                            for query in member_response.citations.search_queries:
                                md_lines.append(f"- {query}")
                            md_lines.append("")  # Empty line before URLs

                        # Add URL citations
                        md_lines.extend(
                            f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                            for i, citation in enumerate(member_response.citations.urls)
                            if citation.url  # Only include citations with valid URLs
                        )

                        md_content = "\n".join(md_lines)
                        if md_content:
                            citations_panel = create_panel(
                                content=Markdown(md_content),
                                title="Citations",
                                border_style="magenta",
                            )
                            panels.append(citations_panel)

                live_console.update(Group(*panels))

            response_content_batch: Union[str, JSON, Markdown] = _parse_response_content(  # type: ignore
                run_response, tags_to_include_in_markdown, show_markdown=team_markdown
            )

            # Create panel for response
            response_panel = create_panel(
                content=response_content_batch,
                title=f"Response ({response_timer.elapsed:.1f}s)",
                border_style="blue",
            )
            panels.append(response_panel)

            # Add citations
            if run_response.citations is not None and run_response.citations.urls is not None:
                md_lines = []

                # Add search queries if present
                if run_response.citations.search_queries:
                    md_lines.append("**Search Queries:**")
                    for query in run_response.citations.search_queries:
                        md_lines.append(f"- {query}")
                    md_lines.append("")  # Empty line before URLs

                # Add URL citations
                md_lines.extend(
                    f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                    for i, citation in enumerate(run_response.citations.urls)
                    if citation.url  # Only include citations with valid URLs
                )

                md_content = "\n".join(md_lines)
                if md_content:  # Only create panel if there are citations
                    citations_panel = create_panel(
                        content=Markdown(md_content),
                        title="Citations",
                        border_style="green",
                    )
                    panels.append(citations_panel)

            if team.memory_manager is not None:
                if team.memory_manager.memories_updated:
                    memory_panel = create_panel(
                        content=Text("Memories updated"),
                        title="Memories",
                        border_style="green",
                    )
                    panels.append(memory_panel)

            if team.session_summary_manager is not None and team.session_summary_manager.summaries_updated:
                summary_panel = create_panel(
                    content=Text("Session summary updated"),
                    title="Session Summary",
                    border_style="green",
                )
                panels.append(summary_panel)
                team.session_summary_manager.summaries_updated = False

        # Final update to remove the "Working..." status
        panels = [p for p in panels if not isinstance(p, Status)]
        live_console.update(Group(*panels))


async def aprint_response_stream(
    team: "Team",
    input: Union[List, Dict, str, Message, BaseModel, List[Message]],
    console: Optional[Any] = None,
    show_message: bool = True,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    show_member_responses: Optional[bool] = None,
    tags_to_include_in_markdown: Optional[Set[str]] = None,
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    run_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    markdown: bool = False,
    stream_events: bool = False,
    knowledge_filters: Optional[Union[Dict[str, Any], List[FilterExpr]]] = None,
    add_history_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
    add_dependencies_to_context: Optional[bool] = None,
    add_session_state_to_context: Optional[bool] = None,
    metadata: Optional[Dict[str, Any]] = None,
    debug_mode: Optional[bool] = None,
    **kwargs: Any,
) -> None:
    import textwrap

    from rich.console import Group
    from rich.json import JSON
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.status import Status
    from rich.text import Text

    if not tags_to_include_in_markdown:
        tags_to_include_in_markdown = {"think", "thinking"}

    stream_events = True  # With streaming print response, we need to stream intermediate steps

    _response_content: str = ""
    _response_reasoning_content: str = ""
    reasoning_steps: List[ReasoningStep] = []

    # Track tool calls by member and team
    member_tool_calls = {}  # type: ignore
    team_tool_calls: List[ToolExecution] = []

    # Track processed tool calls to avoid duplicates
    processed_tool_calls = set()

    # Track streaming member content and names
    member_streaming_content: Dict[str, str] = {}
    member_names: Dict[str, str] = {}
    # Track order of member appearance
    member_order: List[str] = []

    # Initialize final_panels here
    final_panels = []  # type: ignore

    with Live(console=console) as live_console:
        status = Status("Working...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
        live_console.update(status)
        response_timer = Timer()
        response_timer.start()
        # Flag which indicates if the panels should be rendered
        render = False
        # Panels to be rendered
        panels = [status]
        # First render the message panel if the message is not None
        if input and show_message:
            render = True
            # Convert message to a panel
            message_content = get_text_from_message(input)
            message_panel = create_panel(
                content=Text(message_content, style="green"),
                title="Message",
                border_style="cyan",
            )
            panels.append(message_panel)
        if render:
            live_console.update(Group(*panels))

        # Get response from the team
        team_markdown = None
        member_markdown = {}

        input_content = get_text_from_message(input)

        final_run_response = None
        async for resp in team.arun(  # type: ignore
            input=input,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            stream=True,
            stream_events=stream_events,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            run_id=run_id,
            knowledge_filters=knowledge_filters,
            add_history_to_context=add_history_to_context,
            add_dependencies_to_context=add_dependencies_to_context,
            add_session_state_to_context=add_session_state_to_context,
            dependencies=dependencies,
            metadata=metadata,
            debug_mode=debug_mode,
            yield_run_output=True,
            **kwargs,
        ):
            if team_markdown is None:
                if markdown:
                    team_markdown = True
                else:
                    team_markdown = False

                if team.output_schema is not None:
                    team_markdown = False

            if isinstance(resp, TeamRunOutput):
                final_run_response = resp
                continue

            if isinstance(resp, tuple(get_args(TeamRunOutputEvent))):
                if resp.event == TeamRunEvent.run_content:
                    if isinstance(resp.content, str):
                        _response_content += resp.content
                    elif team.output_schema is not None and isinstance(resp.content, BaseModel):
                        try:
                            _response_content = JSON(resp.content.model_dump_json(exclude_none=True), indent=2)  # type: ignore
                        except Exception as e:
                            log_warning(f"Failed to convert response to JSON: {e}")
                    elif team.output_schema is not None and isinstance(resp.content, dict):
                        try:
                            _response_content = JSON(json.dumps(resp.content), indent=2)  # type: ignore
                        except Exception as e:
                            log_warning(f"Failed to convert response to JSON: {e}")
                    if hasattr(resp, "reasoning_content") and resp.reasoning_content is not None:  # type: ignore
                        _response_reasoning_content += resp.reasoning_content  # type: ignore
                if hasattr(resp, "reasoning_steps") and resp.reasoning_steps is not None:  # type: ignore
                    reasoning_steps = resp.reasoning_steps  # type: ignore

                if resp.event == TeamRunEvent.pre_hook_completed:  # type: ignore
                    if resp.run_input is not None:  # type: ignore
                        input_content = get_text_from_message(resp.run_input.input_content)  # type: ignore

                # Collect team tool calls when they START so the panel appears before member responses
                if resp.event == TeamRunEvent.tool_call_started and resp.tool:  # type: ignore
                    tool = resp.tool  # type: ignore
                    if tool.tool_call_id is not None:
                        tool_id = tool.tool_call_id
                    else:
                        tool_id = str(hash(str(tool)))
                    if tool_id not in processed_tool_calls:
                        processed_tool_calls.add(tool_id)
                        team_tool_calls.append(tool)

                # Update team tool calls when they COMPLETE (replaces the started entry)
                if resp.event == TeamRunEvent.tool_call_completed and resp.tool:  # type: ignore
                    tool = resp.tool  # type: ignore
                    if tool.tool_call_id is not None:
                        tool_id = tool.tool_call_id
                    else:
                        tool_id = str(hash(str(tool)))
                    if tool_id not in processed_tool_calls:
                        processed_tool_calls.add(tool_id)
                        team_tool_calls.append(tool)
                    else:
                        # Update the existing tool call with the completed version
                        for i, existing_tool in enumerate(team_tool_calls):
                            existing_id = (
                                existing_tool.tool_call_id
                                if existing_tool.tool_call_id is not None
                                else str(hash(str(existing_tool)))
                            )
                            if existing_id == tool_id:
                                team_tool_calls[i] = tool
                                break

            # Handle agent member events (these have agent_id/agent_name, not team_id/team_name)
            if (
                show_member_responses
                and isinstance(resp, BaseRunOutputEvent)
                and hasattr(resp, "agent_id")
                and resp.agent_id
            ):
                agent_id = resp.agent_id
                if agent_id not in member_names:
                    member_names[agent_id] = team._get_member_name(agent_id) or getattr(
                        resp, "agent_name", "Team Member"
                    )
                if agent_id not in member_order:
                    member_order.append(agent_id)

                # Accumulate streaming content from member agents
                if resp.event == AgentRunEvent.run_content.value:
                    if isinstance(resp.content, str):
                        if agent_id not in member_streaming_content:
                            member_streaming_content[agent_id] = ""
                        member_streaming_content[agent_id] += resp.content

                # Track member tool calls
                if resp.event == AgentRunEvent.tool_call_started.value and hasattr(resp, "tool") and resp.tool:
                    tool = resp.tool
                    if tool.tool_call_id:
                        tool_id = tool.tool_call_id
                    else:
                        tool_id = str(hash(str(tool)))
                    if agent_id not in member_tool_calls:
                        member_tool_calls[agent_id] = []
                    if tool_id not in processed_tool_calls:
                        processed_tool_calls.add(tool_id)
                        member_tool_calls[agent_id].append(tool)

                if resp.event == AgentRunEvent.tool_call_completed.value and hasattr(resp, "tool") and resp.tool:
                    tool = resp.tool
                    if tool.tool_call_id:
                        tool_id = tool.tool_call_id
                    else:
                        tool_id = str(hash(str(tool)))
                    if agent_id not in member_tool_calls:
                        member_tool_calls[agent_id] = []
                    if tool_id not in processed_tool_calls:
                        processed_tool_calls.add(tool_id)
                        member_tool_calls[agent_id].append(tool)
                    else:
                        # Update existing tool call with completed version
                        for i, existing_tool in enumerate(member_tool_calls[agent_id]):
                            existing_id = (
                                existing_tool.tool_call_id
                                if existing_tool.tool_call_id
                                else str(hash(str(existing_tool)))
                            )
                            if existing_id == tool_id:
                                member_tool_calls[agent_id][i] = tool
                                break

            response_content_stream: Union[str, Markdown] = _response_content
            # Escape special tags before markdown conversion
            if team_markdown:
                escaped_content = escape_markdown_tags(_response_content, tags_to_include_in_markdown)
                response_content_stream = Markdown(escaped_content)

            # Create new panels for each chunk
            panels = []

            # Show status spinner above everything while waiting for response content
            if not _response_content:
                panels.append(status)

            if input_content and show_message:
                render = True
                # Convert message to a panel
                message_panel = create_panel(
                    content=Text(input_content, style="green"),
                    title="Message",
                    border_style="cyan",
                )
                panels.append(message_panel)

            if len(reasoning_steps) > 0 and show_reasoning:
                render = True
                # Create panels for reasoning steps
                for i, step in enumerate(reasoning_steps, 1):
                    reasoning_panel = build_reasoning_step_panel(i, step, show_full_reasoning)
                    panels.append(reasoning_panel)

            if len(_response_reasoning_content) > 0 and show_reasoning:
                render = True
                # Create panel for thinking
                thinking_panel = create_panel(
                    content=Text(_response_reasoning_content),
                    title=f"Thinking ({response_timer.elapsed:.1f}s)",
                    border_style="green",
                )
                panels.append(thinking_panel)

            # Render streaming member panels (tool calls + response, grouped per member)
            if show_member_responses:
                for mid in member_order:
                    m_name = member_names.get(mid, "Team Member")

                    # Show member tool calls if any
                    if mid in member_tool_calls and member_tool_calls[mid]:
                        formatted_calls = format_tool_calls(member_tool_calls[mid])
                        if formatted_calls:
                            console_width = console.width if console else 80
                            panel_width = console_width + 30

                            lines = []
                            for call in formatted_calls:
                                wrapped_call = textwrap.fill(f"• {call}", width=panel_width, subsequent_indent="  ")
                                lines.append(wrapped_call)

                            tool_calls_text = "\n\n".join(lines)

                            member_tool_calls_panel = create_panel(
                                content=tool_calls_text,
                                title=f"{m_name} Tool Calls",
                                border_style="yellow",
                            )
                            panels.append(member_tool_calls_panel)

                    # Show member response content if any
                    if mid in member_streaming_content and member_streaming_content[mid]:
                        m_content: Union[str, Markdown] = member_streaming_content[mid]
                        if markdown:
                            m_content = Markdown(
                                escape_markdown_tags(member_streaming_content[mid], tags_to_include_in_markdown)
                            )

                        member_response_panel = create_panel(
                            content=m_content,
                            title=f"{m_name} Response",
                            border_style="magenta",
                        )
                        panels.append(member_response_panel)

            # Add team tool calls panel after member responses
            if team_tool_calls:
                formatted_calls = format_tool_calls(team_tool_calls)
                if formatted_calls:
                    console_width = console.width if console else 80
                    panel_width = console_width + 30

                    lines = []
                    # Create a set to track already added calls by their string representation
                    added_calls = set()
                    for call in formatted_calls:
                        if call not in added_calls:
                            added_calls.add(call)
                            # Wrap the call text to fit within the panel
                            wrapped_call = textwrap.fill(f"• {call}", width=panel_width, subsequent_indent="  ")
                            lines.append(wrapped_call)

                    # Join with blank lines between items
                    tool_calls_text = "\n\n".join(lines)

                    # Add compression stats if available (don't clear - will be cleared in final_panels)
                    if team.compression_manager is not None and team.compression_manager.stats:
                        stats = team.compression_manager.stats
                        saved = stats.get("original_size", 0) - stats.get("compressed_size", 0)
                        orig = stats.get("original_size", 1)
                        if stats.get("tool_results_compressed", 0) > 0:
                            tool_calls_text += f"\n\ncompressed: {stats.get('tool_results_compressed', 0)} | Saved: {saved:,} chars ({saved / orig * 100:.0f}%)"

                    team_tool_calls_panel = create_panel(
                        content=tool_calls_text,
                        title="Team Tool Calls",
                        border_style="yellow",
                    )
                    panels.append(team_tool_calls_panel)

            # Add the team response panel at the end (only if there's actual content)
            if _response_content:
                render = True
                # Create panel for response
                response_panel = create_panel(
                    content=response_content_stream,
                    title=f"Response ({response_timer.elapsed:.1f}s)",
                    border_style="blue",
                )
                panels.append(response_panel)

            if render or len(panels) > 0:
                live_console.update(Group(*panels))

        response_timer.stop()

        run_response = final_run_response

        # Add citations
        if hasattr(resp, "citations") and resp.citations is not None and resp.citations.urls is not None:
            md_lines = []

            # Add search queries if present
            if resp.citations.search_queries:
                md_lines.append("**Search Queries:**")
                for query in resp.citations.search_queries:
                    md_lines.append(f"- {query}")
                md_lines.append("")  # Empty line before URLs

            # Add URL citations
            md_lines.extend(
                f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                for i, citation in enumerate(resp.citations.urls)
                if citation.url  # Only include citations with valid URLs
            )

            md_content = "\n".join(md_lines)
            if md_content:  # Only create panel if there are citations
                citations_panel = create_panel(
                    content=Markdown(md_content),
                    title="Citations",
                    border_style="green",
                )
                panels.append(citations_panel)
                live_console.update(Group(*panels))

        if team.memory_manager is not None:
            if team.memory_manager.memories_updated:
                memory_panel = create_panel(
                    content=Text("Memories updated"),
                    title="Memories",
                    border_style="green",
                )
                panels.append(memory_panel)
                live_console.update(Group(*panels))

        if team.session_summary_manager is not None and team.session_summary_manager.summaries_updated:
            summary_panel = create_panel(
                content=Text("Session summary updated"),
                title="Session Summary",
                border_style="green",
            )
            panels.append(summary_panel)
            live_console.update(Group(*panels))
            team.session_summary_manager.summaries_updated = False

        # Final update to remove the "Working..." status
        panels = [p for p in panels if not isinstance(p, Status)]

        if markdown:
            if isinstance(team.members, list):
                for member in team.members:
                    if member.id is not None:
                        member_markdown[member.id] = True  # type: ignore

        if isinstance(team.members, list):
            for member in team.members:
                if member.output_schema is not None and member.id is not None:
                    member_markdown[member.id] = False  # type: ignore

        # Final panels assembly - we'll recreate the panels from scratch to ensure correct order
        final_panels = []

        # Start with the message
        if input_content and show_message:
            message_panel = create_panel(
                content=Text(input_content, style="green"),
                title="Message",
                border_style="cyan",
            )
            final_panels.append(message_panel)

        # Add reasoning steps
        if reasoning_steps and show_reasoning:
            for i, step in enumerate(reasoning_steps, 1):
                reasoning_panel = build_reasoning_step_panel(i, step, show_full_reasoning)
                final_panels.append(reasoning_panel)

        # Add thinking panel if available
        if _response_reasoning_content and show_reasoning:
            thinking_panel = create_panel(
                content=Text(_response_reasoning_content),
                title=f"Thinking ({response_timer.elapsed:.1f}s)",
                border_style="green",
            )
            final_panels.append(thinking_panel)

        # Add member tool calls and responses (grouped per member)
        if show_member_responses and run_response is not None and hasattr(run_response, "member_responses"):
            for i, member_response in enumerate(run_response.member_responses):
                member_id = None
                if isinstance(member_response, RunOutput) and member_response.agent_id is not None:
                    member_id = member_response.agent_id
                elif isinstance(member_response, TeamRunOutput) and member_response.team_id is not None:
                    member_id = member_response.team_id

                # Print tool calls
                if member_id:
                    # First add tool calls if any
                    if member_id in member_tool_calls and member_tool_calls[member_id]:
                        formatted_calls = format_tool_calls(member_tool_calls[member_id])
                        if formatted_calls:
                            console_width = console.width if console else 80
                            panel_width = console_width + 30

                            lines = []
                            # Create a set to track already added calls by their string representation
                            added_calls = set()
                            for call in formatted_calls:
                                if call not in added_calls:
                                    added_calls.add(call)
                                    # Wrap the call text to fit within the panel
                                    wrapped_call = textwrap.fill(f"• {call}", width=panel_width, subsequent_indent="  ")
                                    lines.append(wrapped_call)

                            tool_calls_text = "\n\n".join(lines)

                            member_name = team._get_member_name(member_id)
                            member_tool_calls_panel = create_panel(
                                content=tool_calls_text,
                                title=f"{member_name} Tool Calls",
                                border_style="yellow",
                            )
                            final_panels.append(member_tool_calls_panel)

                # Add reasoning steps if any
                reasoning_steps = []
                if member_response.reasoning_steps is not None:
                    reasoning_steps = member_response.reasoning_steps
                if reasoning_steps and show_reasoning:
                    for j, step in enumerate(reasoning_steps, 1):
                        member_reasoning_panel = build_reasoning_step_panel(
                            j, step, show_full_reasoning, color="magenta"
                        )
                        final_panels.append(member_reasoning_panel)

                    # Add reasoning steps if any
                    reasoning_steps = []
                    if hasattr(member_response, "reasoning_steps") and member_response.reasoning_steps is not None:
                        reasoning_steps = member_response.reasoning_steps
                    if reasoning_steps and show_reasoning:
                        for j, step in enumerate(reasoning_steps, 1):
                            member_reasoning_panel = build_reasoning_step_panel(
                                j, step, show_full_reasoning, color="magenta"
                            )
                            final_panels.append(member_reasoning_panel)

                # Then add response
                show_markdown = False
                if isinstance(member_response, RunOutput) and member_response.agent_id is not None:
                    show_markdown = member_markdown.get(member_response.agent_id, False)
                elif isinstance(member_response, TeamRunOutput) and member_response.team_id is not None:
                    show_markdown = member_markdown.get(member_response.team_id, False)

                member_response_content = _parse_response_content(  # type: ignore
                    member_response,
                    tags_to_include_in_markdown,
                    show_markdown=show_markdown,
                )

                member_name = "Team Member"
                if isinstance(member_response, RunOutput) and member_response.agent_id is not None:
                    member_name = team._get_member_name(member_response.agent_id)
                elif isinstance(member_response, TeamRunOutput) and member_response.team_id is not None:
                    member_name = team._get_member_name(member_response.team_id)

                member_response_panel = create_panel(
                    content=member_response_content,
                    title=f"{member_name} Response",
                    border_style="magenta",
                )
                final_panels.append(member_response_panel)

                # Add citations if any
                if member_response.citations is not None and member_response.citations.urls is not None:
                    md_lines = []

                    # Add search queries if present
                    if member_response.citations.search_queries:
                        md_lines.append("**Search Queries:**")
                        for query in member_response.citations.search_queries:
                            md_lines.append(f"- {query}")
                        md_lines.append("")  # Empty line before URLs

                    # Add URL citations
                    md_lines.extend(
                        f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                        for i, citation in enumerate(member_response.citations.urls)
                        if citation.url  # Only include citations with valid URLs
                    )

                    md_content = "\n".join(md_lines)
                    if md_content:  # Only create panel if there are citations
                        citations_panel = create_panel(
                            content=Markdown(md_content),
                            title="Citations",
                            border_style="magenta",
                        )
                        final_panels.append(citations_panel)

        # Add team tool calls after member responses
        if team_tool_calls:
            formatted_calls = format_tool_calls(team_tool_calls)
            if formatted_calls:
                console_width = console.width if console else 80
                panel_width = console_width + 30

                lines = []
                # Create a set to track already added calls by their string representation
                added_calls = set()
                for call in formatted_calls:
                    if call not in added_calls:
                        added_calls.add(call)
                        # Wrap the call text to fit within the panel
                        wrapped_call = textwrap.fill(f"• {call}", width=panel_width, subsequent_indent="  ")
                        lines.append(wrapped_call)

                tool_calls_text = "\n\n".join(lines)

                # Add compression stats at end of tool calls
                if team.compression_manager is not None and team.compression_manager.stats:
                    stats = team.compression_manager.stats
                    saved = stats.get("original_size", 0) - stats.get("compressed_size", 0)
                    orig = stats.get("original_size", 1)
                    if stats.get("tool_results_compressed", 0) > 0:
                        tool_calls_text += f"\n\ncompressed: {stats.get('tool_results_compressed', 0)} | Saved: {saved:,} chars ({saved / orig * 100:.0f}%)"
                    team.compression_manager.stats.clear()

                team_tool_calls_panel = create_panel(
                    content=tool_calls_text,
                    title="Team Tool Calls",
                    border_style="yellow",
                )
                final_panels.append(team_tool_calls_panel)

        # Add team response
        if _response_content:
            response_content_stream = _response_content
            if team_markdown:
                escaped_content = escape_markdown_tags(_response_content, tags_to_include_in_markdown)
                response_content_stream = Markdown(escaped_content)

            response_panel = create_panel(
                content=response_content_stream,
                title=f"Response ({response_timer.elapsed:.1f}s)",
                border_style="blue",
            )
            final_panels.append(response_panel)

        # Add team citations
        if hasattr(resp, "citations") and resp.citations is not None and resp.citations.urls is not None:
            md_lines = []

            # Add search queries if present
            if resp.citations.search_queries:
                md_lines.append("**Search Queries:**")
                for query in resp.citations.search_queries:
                    md_lines.append(f"- {query}")
                md_lines.append("")  # Empty line before URLs

            # Add URL citations
            md_lines.extend(
                f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                for i, citation in enumerate(resp.citations.urls)
                if citation.url  # Only include citations with valid URLs
            )

            md_content = "\n".join(md_lines)
            if md_content:  # Only create panel if there are citations
                citations_panel = create_panel(
                    content=Markdown(md_content),
                    title="Citations",
                    border_style="green",
                )
                final_panels.append(citations_panel)

        # Final update with correctly ordered panels
        live_console.update(Group(*final_panels))


def _parse_response_content(
    run_response: Union[TeamRunOutput, RunOutput],
    tags_to_include_in_markdown: Set[str],
    show_markdown: bool = True,
) -> Any:
    from rich.json import JSON
    from rich.markdown import Markdown

    if isinstance(run_response.content, str):
        if show_markdown:
            escaped_content = escape_markdown_tags(run_response.content, tags_to_include_in_markdown)
            return Markdown(escaped_content)
        else:
            return run_response.get_content_as_string(indent=4)
    elif isinstance(run_response.content, BaseModel):
        try:
            return JSON(run_response.content.model_dump_json(exclude_none=True), indent=2)
        except Exception as e:
            log_warning(f"Failed to convert response to JSON: {e}")
    else:
        import json

        try:
            return JSON(json.dumps(run_response.content), indent=4)
        except Exception as e:
            log_warning(f"Failed to convert response to JSON: {e}")
