from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from agno.os.interfaces.slack.builders import build_pause_message
from agno.os.interfaces.slack.helpers import send_slack_message_async, slack_delivery_kwargs, slack_error_code
from agno.os.interfaces.slack.types import block_to_dict, tool_name
from agno.utils.log import log_error

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

    from agno.os.interfaces.slack.state import StreamState
    from agno.os.interfaces.slack.stream import SlackStream
    from agno.run.requirement import RunRequirement

PAUSE_LABELS = {
    "confirmation": "⏸ *Awaiting approval of* `{tool}`…",
    "user_input": "⏸ *Awaiting input for* `{tool}`…",
    "user_feedback": "⏸ *Awaiting feedback*…",
    "external_execution": "⏸ *Awaiting output for* `{tool}`…",
}

_CARD_FAILED_MESSAGE = "The approval form could not be shown here. Resolve the paused run in AgentOS."


def pause_labels(requirements: List["RunRequirement"]) -> List[str]:
    return [PAUSE_LABELS[r.pause_type].format(tool=tool_name(r)) for r in requirements]


async def finalize_pause(
    *,
    client: "AsyncWebClient",
    stream: Optional["SlackStream"],
    state: "StreamState",
    run_id: str,
    channel: str,
    thread_ts: str,
    requirements: List["RunRequirement"],
    unfurl_links: bool = True,
    unfurl_media: bool = True,
    mrkdwn: bool = True,
) -> Optional[str]:
    # 1. Stop the stream with accumulated content; open cards close as complete so Slack does not show them failed
    if stream is not None:
        chunks = state.resolve_all_pending("complete", suffix="paused")
        try:
            await stream.stop(
                markdown_text=state.flush() if state.has_content() else None,
                chunks=chunks or None,
                session_status="suspended",
            )
        except Exception as exc:
            log_error(f"[HITL] stream.stop failed: run_id={run_id} err={slack_error_code(exc)!r} | {exc}")

    # 2. Post awaiting indicator
    labels = pause_labels(requirements)
    if not labels:
        return None

    try:
        resp = await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="\n".join(labels),
            **slack_delivery_kwargs(unfurl_links, unfurl_media, mrkdwn),
        )
        return resp.get("ts")
    except Exception as exc:
        log_error(f"[HITL] awaiting indicator failed: run_id={run_id} | {exc}")
        return None


async def post_pause_card(
    client: "AsyncWebClient",
    paused_event: Any,
    channel: str,
    thread_ts: str,
    awaiting_ts: Optional[str] = None,
    *,
    owner: Optional[str] = None,
    unfurl_links: bool = True,
    unfurl_media: bool = True,
    mrkdwn: bool = True,
) -> Optional[str]:
    run_id = getattr(paused_event, "run_id", None)
    requirements = list(getattr(paused_event, "active_requirements", None) or [])
    if not run_id or not requirements:
        return None

    try:
        # The card blocks embed untrusted tool-arg text, so unfurl flags must apply here
        blocks = build_pause_message(run_id, requirements, awaiting_ts, owner)
        resp = await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Run paused — please resolve below",
            blocks=[block_to_dict(b) for b in blocks],
            **slack_delivery_kwargs(unfurl_links, unfurl_media, mrkdwn),
        )
        return resp.get("ts")
    except Exception as exc:
        log_error(f"[HITL] post_pause_card failed: run_id={run_id} | {exc}")

    # Without a card the run would wait with no way to resolve it from Slack, so say where to go
    try:
        await send_slack_message_async(
            client,
            channel=channel,
            thread_ts=thread_ts,
            message=_CARD_FAILED_MESSAGE,
            unfurl_links=unfurl_links,
            unfurl_media=unfurl_media,
            mrkdwn=mrkdwn,
        )
    except Exception as exc:
        log_error(f"[HITL] pause card fallback failed: run_id={run_id} | {exc}")
    return None
