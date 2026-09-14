"""Slack agent-session lifecycle with a fallback to the legacy Assistant APIs.

Slack's agent messaging experience exposes ``agents.sessions.setStatus`` and
``agents.sessions.rename``. Apps that have not migrated still run the Assistant
experience, whose ``assistant.threads.*`` methods Slack keeps alive through a
compatibility bridge. ``SlackSessions`` tries the agent API first and switches to
the assistant API for the rest of the process the first time Slack rejects it.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Literal, Optional

from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

from agno.os.interfaces.slack.helpers import slack_error_code
from agno.utils.log import log_debug, log_warning

SessionStatus = Literal["processing", "active", "suspended", "closed"]
SessionApi = Literal["auto", "agents", "assistant"]

# Errors that mean "this workspace or app does not have the agent-session API",
# as opposed to a transient failure that should not flip the mode.
_FALLBACK_ERRORS = frozenset(
    {"unknown_method", "method_deprecated", "missing_scope", "not_allowed_token_type", "invalid_arguments"}
)


class SlackSessions:
    def __init__(
        self,
        client_factory: Callable[[], AsyncWebClient],
        mode: SessionApi = "auto",
        loading_messages: Optional[List[str]] = None,
    ) -> None:
        self._client_factory = client_factory
        self.mode: SessionApi = mode
        self.loading_messages = loading_messages

    def _use_agents_api(self) -> bool:
        return self.mode != "assistant"

    def use_assistant_api(self) -> None:
        """Pin the legacy API; called when Slack sends an Assistant-only event."""
        if self.mode == "auto":
            log_debug("Slack Assistant-view event received; using assistant API from now on")
            self.mode = "assistant"

    def _maybe_fall_back(self, exc: BaseException) -> bool:
        """Return True when the caller should retry through the assistant API."""
        code = slack_error_code(exc)
        if self.mode == "auto" and code in _FALLBACK_ERRORS:
            log_debug(f"Slack agent-session API unavailable ({code}); using assistant API from now on")
            self.mode = "assistant"
            return True
        return False

    async def set_status(
        self,
        channel_id: str,
        thread_ts: str,
        status: SessionStatus,
        *,
        legacy_text: str = "",
    ) -> None:
        """Move the session to ``status``.

        Under the assistant API only a loading text exists: ``processing`` shows
        ``legacy_text`` and every other status clears it.
        """
        client = self._client_factory()
        if self._use_agents_api():
            try:
                await client.agents_sessions_setStatus(channel_id=channel_id, thread_ts=thread_ts, status=status)
                return
            except SlackApiError as exc:
                if not self._maybe_fall_back(exc):
                    log_warning(f"agents.sessions.setStatus failed: {slack_error_code(exc)}")
                    return
            except Exception as exc:
                log_warning(f"agents.sessions.setStatus failed: {exc}")
                return

        kwargs: Dict[str, Any] = {
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "status": legacy_text if status == "processing" else "",
        }
        if status == "processing" and self.loading_messages:
            kwargs["loading_messages"] = self.loading_messages
        try:
            await client.assistant_threads_setStatus(**kwargs)
        except Exception as exc:
            log_warning(f"assistant.threads.setStatus failed: {exc}")

    async def rename(self, channel_id: str, thread_ts: str, title: str) -> None:
        client = self._client_factory()
        if self._use_agents_api():
            try:
                await client.agents_sessions_rename(channel_id=channel_id, thread_ts=thread_ts, title=title)
                return
            except SlackApiError as exc:
                if not self._maybe_fall_back(exc):
                    log_warning(f"agents.sessions.rename failed: {slack_error_code(exc)}")
                    return
            except Exception as exc:
                log_warning(f"agents.sessions.rename failed: {exc}")
                return
        try:
            await client.assistant_threads_setTitle(channel_id=channel_id, thread_ts=thread_ts, title=title)
        except Exception as exc:
            log_warning(f"assistant.threads.setTitle failed: {exc}")

    async def set_suggested_prompts(
        self,
        channel_id: str,
        prompts: List[Dict[str, str]],
        *,
        thread_ts: Optional[str] = None,
    ) -> None:
        """Show ``prompts`` above the composer.

        On the Agent view prompts belong to the Messages tab as a whole and Slack
        rejects a thread, so ``thread_ts`` is only sent under the assistant API.
        """
        if not prompts:
            return
        kwargs: Dict[str, Any] = {"channel_id": channel_id, "prompts": prompts}
        if thread_ts and self.mode == "assistant":
            kwargs["thread_ts"] = thread_ts
        try:
            await self._client_factory().assistant_threads_setSuggestedPrompts(**kwargs)
        except Exception as exc:
            log_warning(f"assistant.threads.setSuggestedPrompts failed: {slack_error_code(exc) or exc}")
