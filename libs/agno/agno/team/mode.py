"""Team execution modes."""

from enum import Enum


class TeamMode(str, Enum):
    """Execution mode for a Team.

    Controls how the team leader coordinates work with member agents.
    """

    coordinate = "coordinate"
    """Default supervisor pattern. Leader picks members, crafts tasks, synthesizes responses."""

    route = "route"
    """Router pattern. Leader routes to a specialist and returns the member's response directly."""

    broadcast = "broadcast"
    """Broadcast pattern. Leader delegates the same task to all members simultaneously."""

    tasks = "tasks"
    """Autonomous task-based execution. Leader decomposes goals into a shared task list,
    delegates tasks to members, and loops until all work is complete."""
