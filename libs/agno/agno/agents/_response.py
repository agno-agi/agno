"""Shared terminal rendering for synchronous and asynchronous external agents."""

from typing import Any, Dict, List, Optional, Union

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.status import Status
from rich.text import Text

from agno.exceptions import AgentRunException, RunCancelledException
from agno.models.response import ToolExecution
from agno.run.agent import RunCancelledEvent, RunContentEvent, RunErrorEvent, RunOutput, RunOutputEvent
from agno.run.base import RunStatus
from agno.utils.response import create_panel, format_tool_calls


class ResponseDisplay:
    def __init__(self, *, label: str, input: Any, markdown: bool, show_message: bool):
        self.label = label
        self.input = input
        self.markdown = markdown
        self.show_message = show_message
        self.content = ""
        self.tools: Dict[str, ToolExecution] = {}
        self.status = RunStatus.running
        self.result: Optional[RunOutput] = None
        self.spinner = Status("Working...", spinner="aesthetic", speed=0.4, refresh_per_second=10)

    def update(self, event: Union[RunOutputEvent, RunOutput]) -> None:
        if isinstance(event, RunOutput):
            self.result = event
            self.status = event.status
            self.content = str(event.content or "")
            self.tools = {tool.tool_call_id or str(index): tool for index, tool in enumerate(event.tools or [])}
        elif isinstance(event, RunContentEvent):
            self.content += event.content if isinstance(event.content, str) else ""
        elif isinstance(event, RunErrorEvent):
            self.status = RunStatus.error
            self.content = str(event.content or "Run failed")
        elif isinstance(event, RunCancelledEvent):
            self.status = RunStatus.cancelled
            self.content = event.reason or "Run cancelled"
        else:
            tool = getattr(event, "tool", None)
            if tool is not None:
                self.tools[tool.tool_call_id or tool.tool_name or str(len(self.tools))] = tool

    def render(self, *, finished: bool = False) -> Group:
        panels: List[RenderableType] = []
        if not finished and self.status == RunStatus.running:
            panels.append(self.spinner)
        if self.show_message and self.input is not None:
            panels.append(create_panel(content=Text(str(self.input)), title="Message", border_style="cyan"))
        if self.tools:
            tool_text = Text("\n".join(f" - {item}" for item in format_tool_calls(list(self.tools.values()))))
            panels.append(create_panel(content=tool_text, title="Tool Calls", border_style="yellow"))
        title, color = f"Response ({self.label})", "blue"
        if self.status == RunStatus.error:
            title, color = "Run failed", "red"
        elif self.status == RunStatus.cancelled:
            title, color = "Run cancelled", "yellow"
        if self.content or finished:
            content = (
                Markdown(self.content)
                if self.markdown and self.status not in (RunStatus.error, RunStatus.cancelled)
                else Text(self.content)
            )
            panels.append(create_panel(content=content, title=title, border_style=color))
        if self.result is not None:
            panels.append(Text(f"Run: {self.result.run_id} | Status: {self.result.status.value}"))
            for warning in (self.result.metadata or {}).get("warnings", []):
                panels.append(create_panel(content=Text(str(warning)), title="Warning", border_style="yellow"))
        return Group(*panels)

    def finish(self, *, raise_on_error: bool) -> RunOutput:
        if self.result is None:
            raise RuntimeError("The response stream ended without a terminal RunOutput")
        if raise_on_error:
            if self.result.status == RunStatus.error:
                raise AgentRunException(str(self.result.content or "Run failed"))
            if self.result.status == RunStatus.cancelled:
                raise RunCancelledException(str(self.result.content or "Run cancelled"))
        return self.result
