import json
from typing import List

from agno.memory.v2.schema import UserMemory
from agno.run.team import TeamRunResponse
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel

console = Console()


def print_chat_history(session_run: TeamRunResponse):
    # -*- Print history
    messages = []
    for m in session_run.messages:
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
            title=f"Chat History for session_id: {session_run.session_id}",
            expand=True,
        )
    )


def render_panel(title: str, content: str) -> Panel:
    return Panel(JSON(content, indent=4), title=title, expand=True)


def print_team_memory(user_id: str, memories: List[UserMemory]):
    # -*- Print memories
    console.print(
        render_panel(
            f"Memories for user_id: {user_id}",
            json.dumps(
                [m.to_dict() for m in memories],
                indent=4,
            ),
        )
    )
