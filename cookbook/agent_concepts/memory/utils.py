import json
from typing import List

from agno.run.response import RunResponse
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel

console = Console()


def print_chat_history(session_runs: List[RunResponse]):
    # -*- Print history
    messages = []
    for run in session_runs:
        for m in run.messages:
            if m.role == "system" and len(messages) > 0:
                # Skip system after the first one
                continue

            message_dict = m.model_dump(
                include={"role", "content", "tool_calls", "from_history"}
            )
            if message_dict["content"] is not None:
                del message_dict["tool_calls"]
            else:
                del message_dict["content"]
            messages.append(message_dict)

    console.print(
        Panel(
            JSON(
                json.dumps(
                    messages,
                ),
                indent=4,
            ),
            title=f"Chat History for session_id: {session_runs[0].session_id}",
            expand=True,
        )
    )
