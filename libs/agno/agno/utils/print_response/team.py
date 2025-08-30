from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Set, Union, get_args

from pydantic import BaseModel

from agno.media import Audio, File, Image, Video
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.reasoning.step import ReasoningStep
from agno.run.agent import RunEvent, RunOutput, ToolCallCompletedEvent
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
    tags_to_include_in_markdown: Optional[Set[str]] = None,
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    markdown: bool = False,
    knowledge_filters: Optional[Dict[str, Any]] = None,
    add_history_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
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
        status = Status("Thinking...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
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
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            stream=False,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            knowledge_filters=knowledge_filters,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            metadata=metadata,
            debug_mode=debug_mode,
            **kwargs,
        )
        response_timer.stop()

        team_markdown = False
        member_markdown = {}
        if markdown:
            for member in team.members:
                if member.id is not None:
                    member_markdown[member.id] = True
            team_markdown = True

        if team.output_schema is not None:
            team_markdown = False

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

        if isinstance(run_response, TeamRunOutput) and run_response.reasoning_content is not None:
            # Create panel for thinking
            thinking_panel = create_panel(
                content=Text(run_response.reasoning_content),
                title=f"Thinking ({response_timer.elapsed:.1f}s)",
                border_style="green",
            )
            panels.append(thinking_panel)
            live_console.update(Group(*panels))

        if isinstance(run_response, TeamRunOutput):
            # Handle member responses
            if team.show_members_responses:
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
                    if member_markdown:
                        if isinstance(member_response, RunOutput) and member_response.agent_id is not None:
                            show_markdown = member_markdown.get(member_response.agent_id, False)
                        elif isinstance(member_response, TeamRunOutput) and member_response.team_id is not None:
                            show_markdown = member_markdown.get(member_response.team_id, False)

                    member_response_content: Union[str, JSON, Markdown] = team._parse_response_content(  # type: ignore
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
                        md_content = "\n".join(
                            f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                            for i, citation in enumerate(member_response.citations.urls)
                            if citation.url  # Only include citations with valid URLs
                        )
                        if md_content:  # Only create panel if there are citations
                            citations_panel = create_panel(
                                content=Markdown(md_content),
                                title="Citations",
                                border_style="magenta",
                            )
                            panels.append(citations_panel)

                live_console.update(Group(*panels))

            # Add team level tool calls panel if available
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

                    team_tool_calls_panel = create_panel(
                        content=tool_calls_text,
                        title="Team Tool Calls",
                        border_style="yellow",
                    )
                    panels.append(team_tool_calls_panel)
                    live_console.update(Group(*panels))

            response_content_batch: Union[str, JSON, Markdown] = team._parse_response_content(  # type: ignore
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
                md_content = "\n".join(
                    f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                    for i, citation in enumerate(run_response.citations.urls)
                    if citation.url  # Only include citations with valid URLs
                )
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

        # Final update to remove the "Thinking..." status
        panels = [p for p in panels if not isinstance(p, Status)]
        live_console.update(Group(*panels))


def print_response_stream(
    team: "Team",
    input: Union[List, Dict, str, Message, BaseModel, List[Message]],
    console: Optional[Any] = None,
    show_message: bool = True,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    tags_to_include_in_markdown: Optional[Set[str]] = None,
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    markdown: bool = False,
    stream_intermediate_steps: bool = False,  # type: ignore
    knowledge_filters: Optional[Dict[str, Any]] = None,
    add_history_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
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

    stream_intermediate_steps = True  # With streaming print response, we need to stream intermediate steps

    _response_content: str = ""
    _response_reasoning_content: str = ""
    reasoning_steps: List[ReasoningStep] = []

    # Track tool calls by member and team
    member_tool_calls = {}  # type: ignore
    team_tool_calls = []  # type: ignore

    # Track processed tool calls to avoid duplicates
    processed_tool_calls = set()

    with Live(console=console) as live_console:
        status = Status("Thinking...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
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
            stream_intermediate_steps=stream_intermediate_steps,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            knowledge_filters=knowledge_filters,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            metadata=metadata,
            debug_mode=debug_mode,
            **kwargs,
        )

        team_markdown = None
        member_markdown = {}

        # Dict to track member response panels by member_id
        member_response_panels = {}

        run_id = None
        for resp in stream_resp:
            run_id = resp.run_id
            if team_markdown is None:
                if markdown:
                    team_markdown = True
                else:
                    team_markdown = False

                if team.output_schema is not None:
                    team_markdown = False

            if isinstance(resp, tuple(get_args(TeamRunOutputEvent))):
                if resp.event == TeamRunEvent.run_content:
                    if isinstance(resp.content, str):
                        _response_content += resp.content
                    elif team.output_schema is not None and isinstance(resp.content, BaseModel):
                        try:
                            _response_content = JSON(resp.content.model_dump_json(exclude_none=True), indent=2)  # type: ignore
                        except Exception as e:
                            log_warning(f"Failed to convert response to JSON: {e}")
                    if hasattr(resp, "reasoning_content") and resp.reasoning_content is not None:  # type: ignore
                        _response_reasoning_content += resp.reasoning_content  # type: ignore
                if hasattr(resp, "reasoning_steps") and resp.reasoning_steps is not None:  # type: ignore
                    reasoning_steps = resp.reasoning_steps  # type: ignore

                # Collect team tool calls, avoiding duplicates
                if isinstance(resp, ToolCallCompletedEvent) and resp.tool:
                    tool = resp.tool
                    # Generate a unique ID for this tool call
                    if tool.tool_call_id:
                        tool_id = tool.tool_call_id
                    else:
                        tool_id = str(hash(str(tool)))
                    if tool_id not in processed_tool_calls:
                        processed_tool_calls.add(tool_id)
                        team_tool_calls.append(tool)

            # Collect member tool calls, avoiding duplicates
            if hasattr(resp, "member_responses") and resp.member_responses:
                for member_response in resp.member_responses:
                    member_id = None
                    if isinstance(member_response, RunOutput) and member_response.agent_id is not None:
                        member_id = member_response.agent_id
                    elif isinstance(member_response, TeamRunOutput) and member_response.team_id is not None:
                        member_id = member_response.team_id

                    if member_id and hasattr(member_response, "tools") and member_response.tools:
                        if member_id not in member_tool_calls:
                            member_tool_calls[member_id] = []

                        for tool in member_response.tools:
                            # Generate a unique ID for this tool call
                            if tool.tool_call_id:
                                tool_id = tool.tool_call_id
                            else:
                                tool_id = str(hash(str(tool)))
                            if tool_id not in processed_tool_calls:
                                processed_tool_calls.add(tool_id)
                                member_tool_calls[member_id].append(tool)

            response_content_stream: Union[str, Markdown] = _response_content
            # Escape special tags before markdown conversion
            if team_markdown:
                escaped_content = escape_markdown_tags(_response_content, tags_to_include_in_markdown)
                response_content_stream = Markdown(escaped_content)

            # Create new panels for each chunk
            panels = []

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

            if len(reasoning_steps) > 0 and show_reasoning:
                render = True
                # Create panels for reasoning steps
                for i, step in enumerate(reasoning_steps, 1):
                    reasoning_panel = build_reasoning_step_panel(i, step, show_full_reasoning)
                    panels.append(reasoning_panel)

            if len(_response_reasoning_content) > 0:
                render = True
                # Create panel for thinking
                thinking_panel = create_panel(
                    content=Text(_response_reasoning_content),
                    title=f"Thinking ({response_timer.elapsed:.1f}s)",
                    border_style="green",
                )
                panels.append(thinking_panel)
            elif _response_content == "":
                # Keep showing status if no content yet
                panels.append(status)

            # Process member responses and their tool calls
            for member_response in resp.member_responses if hasattr(resp, "member_responses") else []:
                member_id = None
                member_name = "Team Member"
                if isinstance(member_response, RunOutput) and member_response.agent_id is not None:
                    member_id = member_response.agent_id
                    member_name = team._get_member_name(member_id)
                elif isinstance(member_response, TeamRunOutput) and member_response.team_id is not None:
                    member_id = member_response.team_id

                    member_name = team._get_member_name(member_id)

                # If we have tool calls for this member, display them
                if member_id in member_tool_calls and member_tool_calls[member_id]:
                    formatted_calls = format_tool_calls(member_tool_calls[member_id])
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

                # Process member response content
                if team.show_members_responses and member_id is not None:
                    show_markdown = False
                    if markdown:
                        show_markdown = True

                    member_response_content = team._parse_response_content(
                        member_response,
                        tags_to_include_in_markdown,
                        show_markdown=show_markdown,
                    )

                    member_response_panel = create_panel(
                        content=member_response_content,
                        title=f"{member_name} Response",
                        border_style="magenta",
                    )

                    panels.append(member_response_panel)

                    # Store for reference
                    if member_id is not None:
                        member_response_panels[member_id] = member_response_panel

            # Add team tool calls panel if available (before the team response)
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

                    team_tool_calls_panel = create_panel(
                        content=tool_calls_text,
                        title="Team Tool Calls",
                        border_style="yellow",
                    )
                    panels.append(team_tool_calls_panel)

            # Add the team response panel at the end
            if response_content_stream:
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
        run_response = team.get_run_output(run_id=run_id)  # type: ignore

        # Add citations
        if hasattr(resp, "citations") and resp.citations is not None and resp.citations.urls is not None:
            md_content = "\n".join(
                f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                for i, citation in enumerate(resp.citations.urls)
                if citation.url  # Only include citations with valid URLs
            )
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

        # Final update to remove the "Thinking..." status
        panels = [p for p in panels if not isinstance(p, Status)]

        if markdown:
            for member in team.members:
                if member.id is not None:
                    member_markdown[member.id] = True

        for member in team.members:
            if member.output_schema is not None and member.id is not None:
                member_markdown[member.id] = False  # type: ignore

        # Final panels assembly - we'll recreate the panels from scratch to ensure correct order
        final_panels = []

        # Start with the message
        if input and show_message:
            message_content = get_text_from_message(input)
            message_panel = create_panel(
                content=Text(message_content, style="green"),
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
        if _response_reasoning_content:
            thinking_panel = create_panel(
                content=Text(_response_reasoning_content),
                title=f"Thinking ({response_timer.elapsed:.1f}s)",
                border_style="green",
            )
            final_panels.append(thinking_panel)

        # Add member tool calls and responses in correct order
        if run_response is not None and hasattr(run_response, "member_responses"):
            for i, member_response in enumerate(run_response.member_responses):  # type: ignore
                member_id = None
                if isinstance(member_response, RunOutput) and member_response.agent_id is not None:
                    member_id = member_response.agent_id
                elif isinstance(member_response, TeamRunOutput) and member_response.team_id is not None:
                    member_id = member_response.team_id

                if member_id:
                    # First add tool calls if any
                    if member_id in member_tool_calls and member_tool_calls[member_id]:
                        formatted_calls = format_tool_calls(member_tool_calls[member_id])
                        if formatted_calls:
                            console_width = console.width if console else 80
                            panel_width = console_width + 30

                            lines = []
                            for call in formatted_calls:
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

                # Then add response
                show_markdown = False
                if isinstance(member_response, RunOutput) and member_response.agent_id is not None:
                    show_markdown = member_markdown.get(member_response.agent_id, False)
                elif isinstance(member_response, TeamRunOutput) and member_response.team_id is not None:
                    show_markdown = member_markdown.get(member_response.team_id, False)

                member_response_content = team._parse_response_content(  # type: ignore
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
                    md_content = "\n".join(
                        f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                        for i, citation in enumerate(member_response.citations.urls)
                        if citation.url  # Only include citations with valid URLs
                    )
                    if md_content:  # Only create panel if there are citations
                        citations_panel = create_panel(
                            content=Markdown(md_content),
                            title="Citations",
                            border_style="magenta",
                        )
                        final_panels.append(citations_panel)

        # Add team tool calls before team response
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
            md_content = "\n".join(
                f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                for i, citation in enumerate(resp.citations.urls)
                if citation.url  # Only include citations with valid URLs
            )
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
    tags_to_include_in_markdown: Optional[Set[str]] = None,
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    markdown: bool = False,
    knowledge_filters: Optional[Dict[str, Any]] = None,
    add_history_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
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
        status = Status("Thinking...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
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
            images=images,
            audio=audio,
            videos=videos,
            files=files,
            stream=False,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            knowledge_filters=knowledge_filters,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            metadata=metadata,
            debug_mode=debug_mode,
            **kwargs,
        )
        response_timer.stop()

        team_markdown = False
        member_markdown = {}
        if markdown:
            for member in team.members:
                if member.id is not None:
                    member_markdown[member.id] = True
            team_markdown = True

        if team.output_schema is not None:
            team_markdown = False

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

        if isinstance(run_response, TeamRunOutput) and run_response.reasoning_content is not None:
            # Create panel for thinking
            thinking_panel = create_panel(
                content=Text(run_response.reasoning_content),
                title=f"Thinking ({response_timer.elapsed:.1f}s)",
                border_style="green",
            )
            panels.append(thinking_panel)
            live_console.update(Group(*panels))

        if isinstance(run_response, TeamRunOutput):
            # Handle member responses
            if team.show_members_responses:
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

                    member_response_content: Union[str, JSON, Markdown] = team._parse_response_content(  # type: ignore
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
                        md_content = "\n".join(
                            f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                            for i, citation in enumerate(member_response.citations.urls)
                            if citation.url  # Only include citations with valid URLs
                        )
                        if md_content:
                            citations_panel = create_panel(
                                content=Markdown(md_content),
                                title="Citations",
                                border_style="magenta",
                            )
                            panels.append(citations_panel)

                live_console.update(Group(*panels))

            # Add team level tool calls panel if available
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

                    team_tool_calls_panel = create_panel(
                        content=tool_calls_text,
                        title="Team Tool Calls",
                        border_style="yellow",
                    )
                    panels.append(team_tool_calls_panel)
                    live_console.update(Group(*panels))

            response_content_batch: Union[str, JSON, Markdown] = team._parse_response_content(  # type: ignore
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
                md_content = "\n".join(
                    f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                    for i, citation in enumerate(run_response.citations.urls)
                    if citation.url  # Only include citations with valid URLs
                )
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

        # Final update to remove the "Thinking..." status
        panels = [p for p in panels if not isinstance(p, Status)]
        live_console.update(Group(*panels))


async def aprint_response_stream(
    team: "Team",
    input: Union[List, Dict, str, Message, BaseModel, List[Message]],
    console: Optional[Any] = None,
    show_message: bool = True,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    tags_to_include_in_markdown: Optional[Set[str]] = None,
    session_id: Optional[str] = None,
    session_state: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    audio: Optional[Sequence[Audio]] = None,
    images: Optional[Sequence[Image]] = None,
    videos: Optional[Sequence[Video]] = None,
    files: Optional[Sequence[File]] = None,
    markdown: bool = False,
    stream_intermediate_steps: bool = False,  # type: ignore
    knowledge_filters: Optional[Dict[str, Any]] = None,
    add_history_to_context: Optional[bool] = None,
    dependencies: Optional[Dict[str, Any]] = None,
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

    stream_intermediate_steps = True  # With streaming print response, we need to stream intermediate steps

    _response_content: str = ""
    _response_reasoning_content: str = ""
    reasoning_steps: List[ReasoningStep] = []

    # Track tool calls by member and team
    member_tool_calls = {}  # type: ignore
    team_tool_calls: List[ToolExecution] = []

    # Track processed tool calls to avoid duplicates
    processed_tool_calls = set()

    # Initialize final_panels here
    final_panels = []  # type: ignore

    with Live(console=console) as live_console:
        status = Status("Thinking...", spinner="aesthetic", speed=0.4, refresh_per_second=10)
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

        run_id = None
        async for resp in team.arun(  # type: ignore
            input=input,
            audio=audio,
            images=images,
            videos=videos,
            files=files,
            stream=True,
            stream_intermediate_steps=stream_intermediate_steps,
            session_id=session_id,
            session_state=session_state,
            user_id=user_id,
            knowledge_filters=knowledge_filters,
            add_history_to_context=add_history_to_context,
            dependencies=dependencies,
            metadata=metadata,
            debug_mode=debug_mode,
            **kwargs,
        ):
            run_id = resp.run_id
            if team_markdown is None:
                if markdown:
                    team_markdown = True
                else:
                    team_markdown = False

                if team.output_schema is not None:
                    team_markdown = False

            if isinstance(resp, tuple(get_args(TeamRunOutputEvent))):
                if resp.event == TeamRunEvent.run_content:
                    if isinstance(resp.content, str):
                        _response_content += resp.content
                    elif team.output_schema is not None and isinstance(resp.content, BaseModel):
                        try:
                            _response_content = JSON(resp.content.model_dump_json(exclude_none=True), indent=2)  # type: ignore
                        except Exception as e:
                            log_warning(f"Failed to convert response to JSON: {e}")
                    if hasattr(resp, "reasoning_content") and resp.reasoning_content is not None:  # type: ignore
                        _response_reasoning_content += resp.reasoning_content  # type: ignore
                if hasattr(resp, "reasoning_steps") and resp.reasoning_steps is not None:  # type: ignore
                    reasoning_steps = resp.reasoning_steps  # type: ignore

                # Collect team tool calls, avoiding duplicates
                if isinstance(resp, ToolCallCompletedEvent) and resp.tool:
                    tool = resp.tool
                    # Generate a unique ID for this tool call
                    if tool.tool_call_id is not None:
                        tool_id = tool.tool_call_id
                    else:
                        tool_id = str(hash(str(tool)))
                    if tool_id not in processed_tool_calls:
                        processed_tool_calls.add(tool_id)
                        team_tool_calls.append(tool)

            # Collect member tool calls, avoiding duplicates
            if hasattr(resp, "member_responses") and resp.member_responses:
                for member_response in resp.member_responses:
                    member_id = None
                    if isinstance(member_response, RunOutput) and member_response.agent_id is not None:
                        member_id = member_response.agent_id
                    elif isinstance(member_response, TeamRunOutput) and member_response.team_id is not None:
                        member_id = member_response.team_id

                    if member_id and hasattr(member_response, "tools") and member_response.tools:
                        if member_id not in member_tool_calls:
                            member_tool_calls[member_id] = []

                        for tool in member_response.tools:
                            if tool.tool_call_id is not None:
                                tool_id = tool.tool_call_id
                            else:
                                tool_id = str(hash(str(tool)))
                            if tool_id not in processed_tool_calls:
                                processed_tool_calls.add(tool_id)
                                member_tool_calls[member_id].append(tool)

            response_content_stream: Union[str, Markdown] = _response_content
            # Escape special tags before markdown conversion
            if team_markdown:
                escaped_content = escape_markdown_tags(_response_content, tags_to_include_in_markdown)
                response_content_stream = Markdown(escaped_content)

            # Create new panels for each chunk
            panels = [status]

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

            if len(reasoning_steps) > 0 and show_reasoning:
                render = True
                # Create panels for reasoning steps
                for i, step in enumerate(reasoning_steps, 1):
                    reasoning_panel = build_reasoning_step_panel(i, step, show_full_reasoning)
                    panels.append(reasoning_panel)
            if render:
                live_console.update(Group(*panels))

            if len(_response_reasoning_content) > 0:
                render = True
                # Create panel for thinking
                thinking_panel = create_panel(
                    content=Text(_response_reasoning_content),
                    title=f"Thinking ({response_timer.elapsed:.1f}s)",
                    border_style="green",
                )
                panels.append(thinking_panel)
            if render:
                live_console.update(Group(*panels))

            # Add tool calls panel if available
            if (
                resp is not None
                and hasattr(resp, "tool")
                and resp.tool is not None
                and resp.event == RunEvent.tool_call_started
            ):
                render = True
                # Create bullet points for each tool call
                tool_calls_content = Text()
                formatted_tool_call = format_tool_calls([resp.tool])
                tool_calls_content.append(f"• {formatted_tool_call}\n")

                tool_calls_panel = create_panel(
                    content=tool_calls_content.plain.rstrip(),
                    title="Tool Calls",
                    border_style="yellow",
                )
                panels.append(tool_calls_panel)

            if response_content_stream:
                render = True
                # Create panel for response
                response_panel = create_panel(
                    content=response_content_stream,
                    title=f"Response ({response_timer.elapsed:.1f}s)",
                    border_style="blue",
                )
                panels.append(response_panel)
            if render:
                live_console.update(Group(*panels))
        response_timer.stop()

        run_response = team.get_run_output(run_id=run_id)  # type: ignore

        # Add citations
        if hasattr(resp, "citations") and resp.citations is not None and resp.citations.urls is not None:
            md_content = "\n".join(
                f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                for i, citation in enumerate(resp.citations.urls)
                if citation.url  # Only include citations with valid URLs
            )
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

        # Final update to remove the "Thinking..." status
        panels = [p for p in panels if not isinstance(p, Status)]

        if markdown:
            for member in team.members:
                if member.id is not None:
                    member_markdown[member.id] = True  # type: ignore

        for member in team.members:
            if member.output_schema is not None and member.id is not None:
                member_markdown[member.id] = False  # type: ignore

        # Final panels assembly - we'll recreate the panels from scratch to ensure correct order
        final_panels = []

        # Start with the message
        if input and show_message:
            message_content = get_text_from_message(input)
            message_panel = create_panel(
                content=Text(message_content, style="green"),
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
        if _response_reasoning_content:
            thinking_panel = create_panel(
                content=Text(_response_reasoning_content),
                title=f"Thinking ({response_timer.elapsed:.1f}s)",
                border_style="green",
            )
            final_panels.append(thinking_panel)

        # Add member tool calls and responses in correct order
        if run_response is not None and hasattr(run_response, "member_responses"):
            for i, member_response in enumerate(run_response.member_responses):
                member_id = None
                if isinstance(member_response, RunOutput) and member_response.agent_id is not None:
                    member_id = member_response.agent_id
                elif isinstance(member_response, TeamRunOutput) and member_response.team_id is not None:
                    member_id = member_response.team_id

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

                    member_response_content = team._parse_response_content(  # type: ignore
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
                        md_content = "\n".join(
                            f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                            for i, citation in enumerate(member_response.citations.urls)
                            if citation.url  # Only include citations with valid URLs
                        )
                        if md_content:  # Only create panel if there are citations
                            citations_panel = create_panel(
                                content=Markdown(md_content),
                                title="Citations",
                                border_style="magenta",
                            )
                            final_panels.append(citations_panel)

        # Add team tool calls before team response
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
            md_content = "\n".join(
                f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
                for i, citation in enumerate(resp.citations.urls)
                if citation.url  # Only include citations with valid URLs
            )
            if md_content:  # Only create panel if there are citations
                citations_panel = create_panel(
                    content=Markdown(md_content),
                    title="Citations",
                    border_style="green",
                )
                final_panels.append(citations_panel)

        # Final update with correctly ordered panels
        live_console.update(Group(*final_panels))
