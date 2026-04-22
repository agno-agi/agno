"""
Slack Context Provider
======================

Read-only Slack access for the calling agent — search the workspace,
read channels, expand threads, resolve users. Sends / uploads /
downloads are explicitly disabled; this provider is for *reading
Slack as context*, not for posting to it.

Uses ``SLACK_BOT_TOKEN`` (bot tokens start with ``xoxb-``). Falls back
to ``SLACK_TOKEN`` since that's the variable agno's ``SlackTools``
documents.
"""

from __future__ import annotations

from os import getenv
from typing import TYPE_CHECKING

from agno.agent import Agent
from agno.context._utils import answer_from_run
from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Status
from agno.tools.slack import SlackTools

if TYPE_CHECKING:
    from agno.models.base import Model


class SlackContextProvider(ContextProvider):
    """Read-only Slack workspace access."""

    def __init__(
        self,
        *,
        token: str | None = None,
        id: str = "slack",
        name: str = "Slack",
        instructions: str | None = None,
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model)
        self.token = token or getenv("SLACK_BOT_TOKEN") or getenv("SLACK_TOKEN")
        if not self.token:
            raise ValueError("SlackContextProvider: SLACK_BOT_TOKEN (or SLACK_TOKEN) is required")
        self.instructions_text = instructions if instructions is not None else DEFAULT_SLACK_INSTRUCTIONS
        self._tools: SlackTools | None = None
        self._agent: Agent | None = None

    def status(self) -> Status:
        return Status(ok=True, detail="slack (token configured)")

    async def astatus(self) -> Status:
        return self.status()

    def query(self, question: str) -> Answer:
        return answer_from_run(self._ensure_agent().run(question))

    async def aquery(self, question: str) -> Answer:
        return answer_from_run(await self._ensure_agent().arun(question))

    def instructions(self) -> str:
        if self.mode == ContextMode.tools:
            return (
                f"`{self.name}`: `search_workspace` for topic/catch-up queries across the workspace; "
                "`get_channel_history` for latest messages in a known channel; `get_thread(channel_id, ts)` "
                "to expand a thread; `get_channel_info` / `get_user_info` to resolve names. Read-only."
            )
        return f"`{self.name}`: call `{self.query_tool_name}(question)` to search Slack."

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------

    # Wrap in a `query_slack` sub-agent by default — seven flat SlackTools
    # methods (`search_workspace`, `get_channel_history`, `get_thread`,
    # `list_users`, `get_user_info`, `get_channel_info`, `list_channels`)
    # bloat the calling agent's prompt. The sub-agent orchestrates the
    # multi-call dance internally. mode=tools still surfaces them flat.
    def _default_tools(self) -> list:
        return [self._query_tool()]

    def _all_tools(self) -> list:
        return [self._ensure_tools()]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_tools(self) -> SlackTools:
        if self._tools is None:
            self._tools = SlackTools(
                token=self.token,
                enable_send_message=False,
                enable_send_message_thread=False,
                enable_upload_file=False,
                enable_download_file=False,
                enable_list_channels=True,
                enable_get_channel_history=True,
                enable_search_workspace=True,
                enable_get_thread=True,
                enable_list_users=True,
                enable_get_user_info=True,
                enable_get_channel_info=True,
            )
        return self._tools

    def _ensure_agent(self) -> Agent:
        if self._agent is None:
            self._agent = self._build_agent()
        return self._agent

    def _build_agent(self) -> Agent:
        return Agent(
            id=self.id,
            name=self.name,
            role="Answer questions by searching and reading Slack",
            model=self.model,
            instructions=self.instructions_text,
            tools=[self._ensure_tools()],
            markdown=True,
        )


DEFAULT_SLACK_INSTRUCTIONS = """\
You answer questions by searching and reading Slack.

Workflow:
1. **Search first.** `search_workspace(query)` finds messages across the
   workspace — ideal for topic / catch-up / cross-channel questions.
2. **Drill into a channel.** `get_channel_history(channel_id)` for the
   latest top-level messages in a specific channel.
3. **Expand threads.** When a hit has replies, call
   `get_thread(channel_id, ts)` for the full discussion.
4. **Resolve names.** `get_user_info` / `list_users` turn Slack user IDs
   into display names. Don't invent a name when the ID doesn't resolve —
   report the raw user id instead.
5. **Cite.** Every claim should point to channel + author + timestamp.
   Quote message text verbatim; don't paraphrase.

You are read-only. Never send messages, upload, or download. If the
search returns nothing, say so plainly — don't speculate.
"""
