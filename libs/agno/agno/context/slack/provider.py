"""
Slack Context Provider
======================

Read + write access to a Slack workspace via two tools:

- ``query_<id>`` — natural-language workspace reads (search, channel
  history, threads, user / channel lookups).
- ``update_<id>`` — natural-language writes (post a message, reply in
  a thread).

Two sub-agents under the hood so each has only the scopes it needs:
the read sub-agent never sees ``send_message``; the write sub-agent
never sees ``search_workspace`` or ``get_channel_history``. If a
write needs context ("reply to the last message in #bots"), compose
``query_slack`` → ``update_slack`` at the caller.

Uses ``SLACK_BOT_TOKEN`` (bot tokens start with ``xoxb-``). Falls
back to ``SLACK_TOKEN`` since that's the variable agno's
``SlackTools`` documents.
"""

from __future__ import annotations

from os import getenv
from typing import TYPE_CHECKING

from agno.agent import Agent
from agno.context._utils import answer_from_run
from agno.context.mode import ContextMode
from agno.context.provider import Answer, ContextProvider, Status
from agno.run import RunContext
from agno.tools.slack import SlackTools

if TYPE_CHECKING:
    from agno.models.base import Model


class SlackContextProvider(ContextProvider):
    """Read + write access to a Slack workspace via two tools."""

    def __init__(
        self,
        *,
        token: str | None = None,
        id: str = "slack",
        name: str = "Slack",
        read_instructions: str | None = None,
        write_instructions: str | None = None,
        mode: ContextMode = ContextMode.default,
        model: Model | None = None,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model)
        self.token = token or getenv("SLACK_BOT_TOKEN") or getenv("SLACK_TOKEN")
        if not self.token:
            raise ValueError("SlackContextProvider: SLACK_BOT_TOKEN (or SLACK_TOKEN) is required")
        self.read_instructions_text = (
            read_instructions if read_instructions is not None else DEFAULT_SLACK_READ_INSTRUCTIONS
        )
        self.write_instructions_text = (
            write_instructions if write_instructions is not None else DEFAULT_SLACK_WRITE_INSTRUCTIONS
        )
        self._read_tools: SlackTools | None = None
        self._write_tools: SlackTools | None = None
        self._read_agent: Agent | None = None
        self._write_agent: Agent | None = None

    def status(self) -> Status:
        return Status(ok=True, detail="slack (token configured)")

    async def astatus(self) -> Status:
        return self.status()

    # ------------------------------------------------------------------
    # Query / update
    # ------------------------------------------------------------------

    def query(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(self._ensure_read_agent().run(question, **kwargs))

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(await self._ensure_read_agent().arun(question, **kwargs))

    def update(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(self._ensure_write_agent().run(instruction, **kwargs))

    async def aupdate(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(await self._ensure_write_agent().arun(instruction, **kwargs))

    def instructions(self) -> str:
        if self.mode == ContextMode.tools:
            return (
                f"`{self.name}`: `search_workspace` for topic/catch-up queries across the workspace; "
                "`get_channel_history` for latest messages in a known channel; `get_thread(channel_id, ts)` "
                "to expand a thread; `get_channel_info` / `get_user_info` to resolve names. "
                "mode=tools exposes the read toolset only; writes require mode=default (two-tool surface)."
            )
        return (
            f"`{self.name}`: call `{self.query_tool_name}(question)` to read Slack, "
            f"or `{self.update_tool_name}(instruction)` to post a message."
        )

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------

    # Wrap in sub-agents by default — seven flat SlackTools methods bloat
    # the calling agent's prompt, and splitting reads/writes keeps each
    # sub-agent's scope minimal. mode=tools surfaces the read tools flat
    # (write needs sub-agent composition; flat write tools can be added
    # later if someone has a concrete reason).
    def _default_tools(self) -> list:
        return [self._query_tool(), self._update_tool()]

    def _all_tools(self) -> list:
        return [self._ensure_read_tools()]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ensure_read_tools(self) -> SlackTools:
        if self._read_tools is None:
            self._read_tools = SlackTools(
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
        return self._read_tools

    def _ensure_write_tools(self) -> SlackTools:
        # Writer gets just enough to resolve #channel / @user names and post.
        # No search / history / threads / uploads / downloads — if the write
        # instruction needs context, compose query_slack → update_slack at
        # the caller.
        if self._write_tools is None:
            self._write_tools = SlackTools(
                token=self.token,
                enable_send_message=True,
                enable_send_message_thread=True,
                enable_upload_file=False,
                enable_download_file=False,
                enable_list_channels=True,
                enable_get_channel_history=False,
                enable_search_workspace=False,
                enable_get_thread=False,
                enable_list_users=True,
                enable_get_user_info=True,
                enable_get_channel_info=True,
            )
        return self._write_tools

    def _ensure_read_agent(self) -> Agent:
        if self._read_agent is None:
            self._read_agent = self._build_read_agent()
        return self._read_agent

    def _ensure_write_agent(self) -> Agent:
        if self._write_agent is None:
            self._write_agent = self._build_write_agent()
        return self._write_agent

    def _build_read_agent(self) -> Agent:
        return Agent(
            id=f"{self.id}-read",
            name=f"{self.name} Read",
            model=self.model,
            instructions=self.read_instructions_text,
            tools=[self._ensure_read_tools()],
            markdown=True,
        )

    def _build_write_agent(self) -> Agent:
        return Agent(
            id=f"{self.id}-write",
            name=f"{self.name} Write",
            model=self.model,
            instructions=self.write_instructions_text,
            tools=[self._ensure_write_tools()],
            markdown=True,
        )


DEFAULT_SLACK_READ_INSTRUCTIONS = """\
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


DEFAULT_SLACK_WRITE_INSTRUCTIONS = """\
You post messages to Slack on behalf of the caller.

## Workflow

1. **Pass channel names straight through.** `send_message` (and
   `send_message_thread`) accept either a channel ID (`C0123...`)
   or a name like `#releases` — Slack resolves names server-side.
   **Do NOT call `list_channels` to find an ID first.** On large
   workspaces pagination will mask your target and waste calls.
2. **Compose the message exactly.** Preserve the caller's wording
   unless asked to rephrase.
3. **Pick the right tool.**
   - Top-level post: `send_message(channel, text)`.
   - Reply in thread: `send_message_thread(channel, thread_ts, text)`.
4. **Only look things up when necessary.**
   - If a post fails with `channel_not_found`, the name is wrong or
     the channel doesn't exist — report it, don't retry blindly.
   - If a post fails with `not_in_channel`, the bot needs to be
     invited; report that so the caller can add it.
   - User mentions: format as `<@UXXXXXX>`. Use `get_user_info`
     when you already know the user ID; fall back to `list_users`
     only as a last resort (same pagination concern as channels).
5. **Report what you posted**, echoing the destination + the final
   text. If the post errored, return the error verbatim.

## Safety

- One message per instruction unless the caller explicitly asks for
  a series. Never retry on success.
- Don't guess channel or user IDs. If a lookup returns nothing,
  stop and say so; never post to the wrong destination.
"""
