import json

from rich.console import Console
from rich.json import JSON
from rich.panel import Panel

console = Console()


def print_chat_history(team):
    # -*- Print history
    console.print(
        Panel(
            JSON(
                json.dumps(
                    [
                        m.model_dump(include={"role", "content"})
                        for m in team.memory.messages
                    ]
                ),
                indent=4,
            ),
            title=f"Chat History for session_id: {team.session_id}",
            expand=True,
        )
    )


def render_panel(title: str, content: str) -> Panel:
    return Panel(JSON(content, indent=4), title=title, expand=True)


def print_team_memory(team):
    # -*- Print history
    print_chat_history(team)

    # -*- Print memories
    console.print(
        render_panel(
            f"Memories for user_id: {team.user_id}",
            json.dumps(
                [
                    m.model_dump(include={"memory", "input"})
                    for m in team.memory.memories
                ],
                indent=4,
            ),
        )
    )
