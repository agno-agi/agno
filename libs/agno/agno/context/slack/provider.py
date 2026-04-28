"""
Slack Context Provider
======================

Read + write access to a Slack workspace via two tools:

- ``query_<id>`` — natural-language workspace reads (search, channel
  history, threads, user / channel lookups).
- ``update_<id>`` — natural-language writes (post a message, reply in
  a thread).

Separate sub-agents under the hood keep each scope narrow. Bot-token
reads get channel history and thread tools; Slack-interface reads add
assistant search to the same deterministic read surface; writes get
posting plus lookup tools. If a write needs context ("reply to the last
message in #bots"), compose ``query_slack`` → ``update_slack`` at the
caller.

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
        read: bool = True,
        write: bool = True,
    ) -> None:
        super().__init__(id=id, name=name, mode=mode, model=model, read=read, write=write)
        self.token = token or getenv("SLACK_BOT_TOKEN") or getenv("SLACK_TOKEN")
        if not self.token:
            raise ValueError("SlackContextProvider: SLACK_BOT_TOKEN (or SLACK_TOKEN) is required")
        self.read_instructions_text = read_instructions
        self.write_instructions_text = (
            write_instructions if write_instructions is not None else DEFAULT_SLACK_WRITE_INSTRUCTIONS
        )
        # Lazy-initialized tools and agents
        self._bot_read_tools: SlackTools | None = None
        self._assisted_read_tools: SlackTools | None = None
        self._write_tools: SlackTools | None = None
        self._bot_read_agent: Agent | None = None
        self._assisted_read_agent: Agent | None = None
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
        return answer_from_run(self._select_read_agent(run_context).run(question, **kwargs))

    async def aquery(self, question: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(await self._select_read_agent(run_context).arun(question, **kwargs))

    def update(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(self._ensure_write_agent().run(instruction, **kwargs))

    async def aupdate(self, instruction: str, *, run_context: RunContext | None = None) -> Answer:
        kwargs = self._run_kwargs_for_sub_agent(run_context)
        return answer_from_run(await self._ensure_write_agent().arun(instruction, **kwargs))

    def instructions(self) -> str:
        """Generate guidance for the calling agent based on mode.

        tools  — raw SlackTools surface, caller manages tool calls directly
        agent  — read-only query tool, no write access
        default — both query and update tools via sub-agents
        """
        if self.mode == ContextMode.tools:
            return (
                f"`{self.name}`: `get_channel_history(channel)` for latest messages in a known channel; "
                "`get_thread(channel, ts)` to expand a thread; `get_channel_info` / `get_user_info` "
                "to resolve names. Pass channel names like `#agents` directly."
            )
        if self.mode == ContextMode.agent:
            return f"`{self.name}`: call `{self.query_tool_name}(question)` to read Slack."
        return (
            f"`{self.name}`: call `{self.query_tool_name}(question)` to read Slack. "
            f"Use `{self.update_tool_name}(instruction)` to post a message."
        )

    # ------------------------------------------------------------------
    # Mode resolution
    # ------------------------------------------------------------------
    # Sub-agents by default — seven flat SlackTools methods bloat the
    # calling agent's prompt. Splitting reads/writes keeps each sub-agent
    # scope minimal. mode=tools surfaces raw read tools for direct use.

    def _default_tools(self) -> list:
        return self._read_write_tools()

    def _query_tool(self):
        query_tool = super()._query_tool()
        query_tool.description = (
            "Read Slack with a natural-language request. Use for channel history, workspace search, "
            "threads, and user or channel lookups."
        )
        return query_tool

    def _update_tool(self):
        update_tool = super()._update_tool()
        update_tool.description = (
            "Post a Slack message or thread reply with a natural-language instruction. Include the "
            "destination channel and the exact message to send. If the user asks to post, send, or "
            "share something in Slack, call this tool before the final response. Only report that "
            "posting is unavailable when this tool returns an error."
        )
        return update_tool

    def _all_tools(self) -> list:
        # mode=tools is static: the provider cannot know whether a future
        # tool call will carry Slack interface metadata. Expose the
        # bot-token-compatible read surface so terminal runs never see the
        # action-token-only search_workspace tool.
        return [self._ensure_bot_read_tools()]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _has_action_token(run_context: RunContext | None) -> bool:
        return bool(run_context and run_context.metadata and run_context.metadata.get("action_token"))

    def _select_read_agent(self, run_context: RunContext | None) -> Agent:
        if self._has_action_token(run_context):
            return self._ensure_assisted_read_agent()
        return self._ensure_bot_read_agent()

    def _read_instructions(self, default: str) -> str:
        return self.read_instructions_text if self.read_instructions_text is not None else default

    # ------------------------------------------------------------------
    # Lazy initialization (standard _ensure_* pattern)
    # ------------------------------------------------------------------

    def _ensure_bot_read_tools(self) -> SlackTools:
        if self._bot_read_tools is None:
            self._bot_read_tools = SlackTools(
                token=self.token,
                enable_send_message=False,
                enable_send_message_thread=False,
                enable_upload_file=False,
                enable_download_file=False,
                enable_list_channels=True,
                enable_get_channel_history=True,
                enable_search_workspace=False,
                enable_get_thread=True,
                enable_list_users=True,
                enable_get_user_info=True,
                enable_get_channel_info=True,
            )
        return self._bot_read_tools

    def _ensure_assisted_read_tools(self) -> SlackTools:
        if self._assisted_read_tools is None:
            self._assisted_read_tools = SlackTools(
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
        return self._assisted_read_tools

    def _ensure_write_tools(self) -> SlackTools:
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

    def _ensure_bot_read_agent(self) -> Agent:
        if self._bot_read_agent is None:
            self._bot_read_agent = Agent(
                id=f"{self.id}-bot-read",
                name=f"{self.name} Bot Read",
                model=self.model,
                instructions=self._read_instructions(_SLACK_BOT_TOKEN_READ_INSTRUCTIONS),
                tools=[self._ensure_bot_read_tools()],
                markdown=True,
            )
        return self._bot_read_agent

    def _ensure_assisted_read_agent(self) -> Agent:
        if self._assisted_read_agent is None:
            self._assisted_read_agent = Agent(
                id=f"{self.id}-assisted-read",
                name=f"{self.name} Assisted Read",
                model=self.model,
                instructions=self._read_instructions(_SLACK_ASSISTED_READ_INSTRUCTIONS),
                tools=[self._ensure_assisted_read_tools()],
                markdown=True,
            )
        return self._assisted_read_agent

    def _ensure_write_agent(self) -> Agent:
        if self._write_agent is None:
            self._write_agent = Agent(
                id=f"{self.id}-write",
                name=f"{self.name} Write",
                model=self.model,
                instructions=self.write_instructions_text,
                tools=[self._ensure_write_tools()],
                markdown=True,
            )
        return self._write_agent


_SLACK_ASSISTED_READ_INSTRUCTIONS = """\
You answer questions by searching and reading Slack.

Workflow:
1. **Use the deterministic tools for exact reads.** If the user asks for
   recent messages in a specific channel, call
   `get_channel_history(channel)`. If they ask about a thread or a
   message with replies, call `get_thread(channel, ts)`.
2. **Use assistant search for broad reads.** `search_workspace(query)`
   is for topic, catch-up, cross-channel, and fuzzy discovery requests
   across the workspace using the caller's Slack interface permissions.
3. **Shape search queries.** Include channel or topic hints from the
   user's request. Use Slack search filters when useful, e.g.
   `in:#agents`.
4. **Resolve names.** `get_user_info` / `list_users` turn Slack user IDs
   into display names. Don't invent a name when the ID doesn't resolve -
   report the raw user id instead.
5. **Cite.** Every claim should point to channel + author + timestamp
   or permalink. Quote message text verbatim; don't paraphrase.

You are read-only. Never send messages, upload, or download. If the
channel cannot be read or search returns nothing, say so plainly - don't
speculate.
"""


_SLACK_BOT_TOKEN_READ_INSTRUCTIONS = """\
You answer questions by reading Slack with bot-token-compatible tools.

Workflow:
1. **Read known channels directly.** If the user provides a channel name
   or ID, pass it straight to `get_channel_history(channel)`. The tool
   resolves names like `#agents` to IDs.
2. **Discover only when needed.** Use `list_channels` only when the user
   did not name a channel. The bot must be a member of private channels.
3. **Expand threads.** When a message has replies, call
   `get_thread(channel, ts)` for the full discussion. Pass the same
   channel name or ID you used for history.
4. **Resolve names.** `get_user_info` / `list_users` turn Slack user IDs
   into display names. Don't invent a name when the ID doesn't resolve —
   report the raw user id instead.
5. **Cite.** Every claim should point to channel + author + timestamp.
   Quote message text verbatim; don't paraphrase.

You are read-only. Never send messages, upload, or download. If the
channel cannot be found or the bot is not a member, say so plainly.
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
