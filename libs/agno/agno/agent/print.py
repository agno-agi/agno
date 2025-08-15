import json
from collections.abc import Set
from typing import List, Optional, Union, get_args

from pydantic import BaseModel
from rich.json import JSON
from rich.markdown import Markdown
from rich.text import Text

from agno.reasoning.step import ReasoningStep
from agno.run.response import RunEvent, RunOutput, RunOutputEvent
from agno.utils.log import log_warning
from agno.utils.response import create_panel, create_paused_run_output_panel, escape_markdown_tags, format_tool_calls
from agno.utils.timer import Timer


def build_panels_stream(
    response_content: Union[str, JSON, Markdown],
    response_event: RunOutputEvent,
    response_timer: Timer,
    response_thinking_buffer: str,
    reasoning_steps: List[ReasoningStep],
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
):
    panels = []

    if len(reasoning_steps) > 0 and show_reasoning:
        # Create panels for reasoning steps
        for i, step in enumerate(reasoning_steps, 1):
            # Build step content
            step_content = Text.assemble()
            if step.title is not None:
                step_content.append(f"{step.title}\n", "bold")
            if step.action is not None:
                step_content.append(Text.from_markup(f"[bold]Action:[/bold] {step.action}\n", style="dim"))
            if step.result is not None:
                step_content.append(Text.from_markup(step.result, style="dim"))

            if show_full_reasoning:
                # Add detailed reasoning information if available
                if step.reasoning is not None:
                    step_content.append(Text.from_markup(f"\n[bold]Reasoning:[/bold] {step.reasoning}", style="dim"))
                if step.confidence is not None:
                    step_content.append(Text.from_markup(f"\n[bold]Confidence:[/bold] {step.confidence}", style="dim"))
            reasoning_panel = create_panel(content=step_content, title=f"Reasoning step {i}", border_style="green")
            panels.append(reasoning_panel)

    if len(response_thinking_buffer) > 0:
        # Create panel for thinking
        thinking_panel = create_panel(
            content=Text(response_thinking_buffer),
            title=f"Thinking ({response_timer.elapsed:.1f}s)",
            border_style="green",
        )
        panels.append(thinking_panel)

    # Add tool calls panel if available
    if (
        hasattr(response_event, "tool")
        and response_event.tool is not None
        and response_event.event == RunEvent.tool_call_started
    ):
        # Create bullet points for each tool call
        tool_calls_content = Text()
        formatted_tool_call = format_tool_calls([response_event.tool])
        tool_calls_content.append(f"• {formatted_tool_call}\n")

        tool_calls_panel = create_panel(
            content=tool_calls_content.plain.rstrip(),
            title="Tool Calls",
            border_style="yellow",
        )
        panels.append(tool_calls_panel)

    response_panel = None
    if response_content:
        response_panel = create_panel(
            content=response_content,
            title=f"Response ({response_timer.elapsed:.1f}s)",
            border_style="blue",
        )
        panels.append(response_panel)

    if (
        isinstance(response_event, tuple(get_args(RunOutputEvent)))
        and hasattr(response_event, "citations")
        and response_event.citations is not None
        and response_event.citations.urls is not None
    ):
        md_content = "\n".join(
            f"{i + 1}. [{citation.title or citation.url}]({citation.url})"
            for i, citation in enumerate(response_event.citations.urls)
            if citation.url  # Only include citations with valid URLs
        )
        if md_content:  # Only create panel if there are citations
            citations_panel = create_panel(
                content=Markdown(md_content),
                title="Citations",
                border_style="green",
            )
            panels.append(citations_panel)

    return panels


def build_panels(
    run_response: RunOutput,
    response_timer: Timer,
    response_model: Optional[BaseModel] = None,
    show_reasoning: bool = True,
    show_full_reasoning: bool = False,
    tags_to_include_in_markdown: Optional[Set[str]] = None,
    markdown: bool = False,
):
    panels = []

    reasoning_steps = []

    if isinstance(run_response, RunOutput) and run_response.is_paused:
        response_panel = create_paused_run_output_panel(run_response)
        panels.append(response_panel)
        return panels

    if (
        isinstance(run_response, RunOutput)
        and run_response.metadata is not None
        and run_response.metadata.reasoning_steps is not None
    ):
        reasoning_steps = run_response.metadata.reasoning_steps

    if len(reasoning_steps) > 0 and show_reasoning:
        # Create panels for reasoning steps
        for i, step in enumerate(reasoning_steps, 1):
            # Build step content
            step_content = Text.assemble()
            if step.title is not None:
                step_content.append(f"{step.title}\n", "bold")
            if step.action is not None:
                step_content.append(Text.from_markup(f"[bold]Action:[/bold] {step.action}\n", style="dim"))
            if step.result is not None:
                step_content.append(Text.from_markup(step.result, style="dim"))

            if show_full_reasoning:
                # Add detailed reasoning information if available
                if step.reasoning is not None:
                    step_content.append(Text.from_markup(f"\n[bold]Reasoning:[/bold] {step.reasoning}", style="dim"))
                if step.confidence is not None:
                    step_content.append(Text.from_markup(f"\n[bold]Confidence:[/bold] {step.confidence}", style="dim"))
            reasoning_panel = create_panel(content=step_content, title=f"Reasoning step {i}", border_style="green")
            panels.append(reasoning_panel)

    if isinstance(run_response, RunOutput) and run_response.thinking is not None:
        # Create panel for thinking
        thinking_panel = create_panel(
            content=Text(run_response.thinking),
            title=f"Thinking ({response_timer.elapsed:.1f}s)",
            border_style="green",
        )
        panels.append(thinking_panel)

    # Add tool calls panel if available
    if isinstance(run_response, RunOutput) and run_response.formatted_tool_calls:
        # Create bullet points for each tool call
        tool_calls_content = Text()
        for formatted_tool_call in run_response.formatted_tool_calls:
            tool_calls_content.append(f"• {formatted_tool_call}\n")

        tool_calls_panel = create_panel(
            content=tool_calls_content.plain.rstrip(),
            title="Tool Calls",
            border_style="yellow",
        )
        panels.append(tool_calls_panel)

    response_content_batch: Union[str, JSON, Markdown] = ""  # type: ignore
    if isinstance(run_response, RunOutput):
        if isinstance(run_response.content, str):
            if markdown:
                escaped_content = escape_markdown_tags(run_response.content, tags_to_include_in_markdown)
                response_content_batch = Markdown(escaped_content)
            else:
                response_content_batch = run_response.get_content_as_string(indent=4)
        elif response_model is not None and isinstance(run_response.content, BaseModel):
            try:
                response_content_batch = JSON(run_response.content.model_dump_json(exclude_none=True), indent=2)
            except Exception as e:
                log_warning(f"Failed to convert response to JSON: {e}")
        else:
            try:
                response_content_batch = JSON(json.dumps(run_response.content), indent=4)
            except Exception as e:
                log_warning(f"Failed to convert response to JSON: {e}")

    # Create panel for response
    response_panel = create_panel(
        content=response_content_batch,
        title=f"Response ({response_timer.elapsed:.1f}s)",
        border_style="blue",
    )
    panels.append(response_panel)

    if (
        isinstance(run_response, RunOutput)
        and run_response.citations is not None
        and run_response.citations.urls is not None
    ):
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

    return panels
