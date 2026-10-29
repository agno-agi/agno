"""Reads of member settings that only native members have.

A team's members can be Agents, sub-Teams or harness agents (Claude Code, Codex). A harness
agent runs its own model and tools, so it has no knowledge base and no storage flags. Team
code reads those settings through these helpers, which give a harness member the defaults.
"""

from typing import TYPE_CHECKING, Any, NamedTuple, Optional

if TYPE_CHECKING:
    from agno.run import RunContext


class MemberStorage(NamedTuple):
    """Which parts of its runs a member stores. Each defaults to True when the member has no setting."""

    media: bool
    tool_messages: bool
    history_messages: bool

    @property
    def keeps_all(self) -> bool:
        return self.media and self.tool_messages and self.history_messages


def member_storage(member: Any) -> MemberStorage:
    """The storage flags of a member, with a harness member keeping everything."""
    return MemberStorage(
        media=getattr(member, "store_media", True),
        tool_messages=getattr(member, "store_tool_messages", True),
        history_messages=getattr(member, "store_history_messages", True),
    )


def member_knowledge_filters(member: Any, run_context: "RunContext") -> Optional[Any]:
    """The team run's knowledge filters to pass to a member.

    Only a member with a knowledge base and no filters of its own receives them.
    """
    if not getattr(member, "knowledge_filters", None) and getattr(member, "knowledge", None):
        return run_context.knowledge_filters
    return None
