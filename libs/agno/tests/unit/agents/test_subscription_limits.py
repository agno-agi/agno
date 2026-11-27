"""An agent on a subscription that reaches its usage limit says so plainly.

The limits are read from the shapes the two SDKs define: Claude Code's rate limit event and
assistant error, and Codex's usageLimitExceeded turn error and rate limit windows. No model calls.
"""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest

from agno.agents import _limits
from agno.agents.claude import ClaudeAgent
from agno.agents.claude.agent import ClaudeResultError
from agno.agents.codex import CodexAgent
from agno.run.base import RunStatus
from tests.unit.agents.test_claude import (  # noqa: F401
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    fake_sdk,
    scripted,
)

# 2026-11-28 14:00 UTC
RESETS_AT = 1795874400


@dataclass
class RateLimitEvent:
    """Claude Code's rate_limit_event, as claude_agent_sdk.RateLimitEvent carries it."""

    rate_limit_info: Any
    uuid: str = "u-limit"
    session_id: str = "sdk-1"


def rate_limit(status: str = "rejected", kind: Optional[str] = "five_hour", **fields: Any) -> RateLimitEvent:
    info = SimpleNamespace(status=status, resets_at=RESETS_AT, rate_limit_type=kind, overage_status=None)
    info.__dict__.update(fields)
    return RateLimitEvent(info)


@pytest.fixture
def notes(monkeypatch) -> List[str]:
    logged: List[str] = []
    monkeypatch.setattr(_limits, "log_warning", logged.append)
    return logged


@pytest.fixture(autouse=True)
def api_keys_on_the_host(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-key")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("CODEX_ACCESS_TOKEN", raising=False)


# ---------------------------------------------------------------------------
# The sentence
# ---------------------------------------------------------------------------


def test_the_message_names_the_agent_the_limit_and_when_it_resets():
    assert _limits.resets_at_text(RESETS_AT) == "2026-11-28 14:00 UTC"
    assert _limits.limit_message("claude-1", "Claude", "five-hour", RESETS_AT, "You hit your limit", "Claude Code") == (
        "claude-1 has reached its Claude subscription limit (the five-hour limit); it resets at "
        "2026-11-28 14:00 UTC. No API key was used. Claude Code said: You hit your limit"
    )
    # With nothing more from the harness, only what is known is said.
    assert _limits.limit_message("codex-1", "ChatGPT", None, None, None, "Codex") == (
        "codex-1 has reached its ChatGPT subscription limit. No API key was used."
    )
    for unusable in (None, 0, -1, "soon", True):
        assert _limits.resets_at_text(unusable) is None


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stream", [False, True], ids=["arun", "stream"])
async def test_claude_on_a_subscription_says_its_limit_is_reached_and_when_it_resets(scripted, stream):  # noqa: F811
    turns, calls, _ = scripted
    turns.append(
        [
            SystemMessage("init", {"session_id": "sdk-1"}),
            rate_limit(kind="seven_day"),
            AssistantMessage(content=[], error="rate_limit"),
            ResultMessage("sdk-1", "You've hit your weekly limit · resets Nov 28", is_error=True),
        ]
    )
    agent = ClaudeAgent(id="claude-1", oauth_token="oauth-token-1", retries=2, delay_between_retries=0)
    if stream:
        events = [event async for event in agent.arun("go", session_id="s", stream=True)]
        content = events[-1].content
    else:
        run = await agent.arun("go", session_id="s")
        assert run.status == RunStatus.error
        content = run.content
    assert str(content).startswith(
        "claude-1 has reached its Claude subscription limit (the weekly limit); it resets at "
        "2026-11-28 14:00 UTC. No API key was used. Claude Code said: "
    )
    assert "You've hit your weekly limit" in str(content)
    # Running it again would fail the same way until the limit resets: it is not retried.
    assert len(calls) == 1


def test_claude_reads_either_report_of_the_limit(notes):
    agent = ClaudeAgent(id="claude-1", oauth_token="oauth-token-1")
    plain = ClaudeResultError("Claude SDK error: limit reached", subtype="success", assistant_error="rate_limit")
    # The assistant error alone: the limit is named, with no time to give.
    said = agent._subscription_limit(plain, None)
    assert said.subscription_limit and str(said).startswith(
        "claude-1 has reached its Claude subscription limit. No API key was used. Claude Code said: "
    )
    # The rejected event alone, for each limit Claude Code names.
    for kind, name in (("five_hour", "five-hour"), ("seven_day_opus", "weekly Opus"), ("overage", "extra usage")):
        other = ClaudeResultError("Claude SDK error: stopped", subtype="success")
        said = agent._subscription_limit(other, rate_limit(kind=kind).rate_limit_info)
        assert f"(the {name} limit); it resets at 2026-11-28 14:00 UTC" in str(said)
    assert not agent._is_retryable_error(said)
    assert notes == []


def test_a_claude_failure_that_is_not_the_limit_is_left_as_it_is(notes):
    agent = ClaudeAgent(id="claude-1", oauth_token="oauth-token-1")
    # Extra usage carried the run past the limit, so its later failure is about something else.
    paid = rate_limit(overage_status="allowed").rate_limit_info
    other = ClaudeResultError("Claude SDK error: 529 Overloaded", subtype="success")
    assert agent._subscription_limit(other, paid) is other
    # A turn limit of the agent's own is not the subscription's.
    turns = ClaudeResultError("Claude SDK error", subtype="error_max_turns")
    assert agent._subscription_limit(turns, rate_limit().rate_limit_info) is turns
    assert notes == []
    # A failure that reads like a limit, in a shape this code does not know, is logged with its text.
    odd = ClaudeResultError("Claude SDK error: usage quota exhausted for this organisation", subtype="success")
    assert agent._subscription_limit(odd, None) is odd
    assert len(notes) == 1 and "claude-1" in notes[0] and "usage quota exhausted" in notes[0]


def test_claude_on_an_api_key_is_untouched(notes):
    agent = ClaudeAgent(id="claude-key")
    limited = ClaudeResultError("Claude SDK error: 429 rate limit", subtype="success", assistant_error="rate_limit")
    assert agent._subscription_limit(limited, rate_limit().rate_limit_info) is limited
    assert agent._is_retryable_error(limited)
    assert notes == []


def test_claude_inside_a_sandbox_knows_it_is_on_a_subscription(monkeypatch):
    # In a sandbox the agent has no oauth_token setting: only the variable, and no API key.
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-token-1")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    limited = ClaudeResultError("Claude SDK error: limit", subtype="success", assistant_error="rate_limit")
    assert str(ClaudeAgent(id="claude-1")._subscription_limit(limited, None)).startswith(
        "claude-1 has reached its Claude subscription limit."
    )


# ---------------------------------------------------------------------------
# Codex
# ---------------------------------------------------------------------------


def window(used_percent: int, minutes: Optional[int], resets_at: Optional[int] = RESETS_AT) -> Any:
    """A RateLimitWindow of account/rateLimits/read."""
    return SimpleNamespace(used_percent=used_percent, window_duration_mins=minutes, resets_at=resets_at)


def codex_client(primary: Any = None, secondary: Any = None, fails: bool = False) -> Any:
    """A Codex client whose app-server answers account/rateLimits/read."""
    asked: List[str] = []

    async def request(method: str, params: Any, *, response_model: Any) -> Any:
        asked.append(method)
        if fails:
            raise RuntimeError("the app-server did not answer")
        return SimpleNamespace(rate_limits=SimpleNamespace(primary=primary, secondary=secondary))

    return SimpleNamespace(_client=SimpleNamespace(request=request), asked=asked)


def on_a_sign_in() -> CodexAgent:
    return CodexAgent(id="codex-1", auth_json={"tokens": {"refresh_token": "r"}})


async def test_codex_on_a_subscription_says_its_limit_is_reached_and_when_it_resets(notes):
    codex = codex_client(primary=window(100, 300), secondary=window(41, 10080, RESETS_AT + 86400))
    message = await on_a_sign_in()._aturn_failure(codex, "You've hit your usage limit.", "usageLimitExceeded")
    assert message == (
        "codex-1 has reached its ChatGPT subscription limit (the five-hour limit); it resets at "
        "2026-11-28 14:00 UTC. No API key was used. Codex said: You've hit your usage limit."
    )
    assert codex.asked == ["account/rateLimits/read"]
    # The weekly window, when that is the full one.
    codex = codex_client(primary=window(12, 300, RESETS_AT - 3600), secondary=window(100, 10080))
    message = await on_a_sign_in()._aturn_failure(codex, "limit", "usageLimitExceeded")
    assert "(the weekly limit); it resets at 2026-11-28 14:00 UTC" in message
    # An access token is a subscription too.
    message = await CodexAgent(id="codex-2", access_token="token")._aturn_failure(codex, "limit", "usageLimitExceeded")
    assert message.startswith("codex-2 has reached its ChatGPT subscription limit (the weekly limit)")
    assert notes == []


@pytest.mark.parametrize(
    "codex",
    [codex_client(fails=True), codex_client(), SimpleNamespace(_client=None)],
    ids=["the read fails", "no windows", "no app-server client"],
)
async def test_codex_says_the_limit_is_reached_without_a_time_when_it_cannot_read_one(codex):
    message = await on_a_sign_in()._aturn_failure(codex, "You've hit your usage limit.", "usageLimitExceeded")
    assert message == (
        "codex-1 has reached its ChatGPT subscription limit. No API key was used. "
        "Codex said: You've hit your usage limit."
    )


async def test_codex_on_an_api_key_is_untouched(notes):
    codex = codex_client(primary=window(100, 300))
    message = await CodexAgent(id="codex-key")._aturn_failure(codex, "Quota exceeded", "usageLimitExceeded")
    assert message == "Codex turn failed: Quota exceeded"
    assert codex.asked == [] and notes == []


async def test_a_codex_failure_that_reads_like_a_limit_is_logged_with_its_text(notes):
    codex = codex_client()
    agent = on_a_sign_in()
    assert await agent._aturn_failure(codex, "stream disconnected", None) == "Codex turn failed: stream disconnected"
    assert notes == []
    odd = await agent._aturn_failure(codex, "Rate limit reached for requests", "rateLimitExceeded")
    assert odd == "Codex turn failed: Rate limit reached for requests"
    assert len(notes) == 1 and "codex-1" in notes[0] and "Rate limit reached for requests" in notes[0]


async def test_codex_inside_a_sandbox_knows_it_is_on_a_subscription(monkeypatch):
    # In a sandbox the agent has no auth_json setting: it has a sign-in file, and no API key in its environment.
    monkeypatch.delenv("OPENAI_API_KEY")
    message = await CodexAgent(id="codex-1")._aturn_failure(codex_client(), "limit", "usageLimitExceeded")
    assert message.startswith("codex-1 has reached its ChatGPT subscription limit.")
