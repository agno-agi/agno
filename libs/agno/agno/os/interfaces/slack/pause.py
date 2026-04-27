from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from agno.os.interfaces.slack.builders import classify_requirement
from agno.os.interfaces.slack.types import LiveStream, _tool_name
from agno.utils.log import log_error, log_info

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

    from agno.run.requirement import RunRequirement


_PAUSE_LABELS = {
    "confirmation": "⏸ *Awaiting approval of* `{tool}`…",
    "user_input": "⏸ *Awaiting input for* `{tool}`…",
    "user_feedback": "⏸ *Awaiting feedback*…",
    "external_execution": "⏸ *Awaiting output for* `{tool}`…",
}


def build_pause_labels(requirements: List["RunRequirement"]) -> List[str]:
    labels: List[str] = []
    for requirement in requirements:
        kind = classify_requirement(requirement)
        tool = _tool_name(requirement)
        labels.append(_PAUSE_LABELS[kind].format(tool=tool))
    return labels


async def finalize_pause(
    *,
    client: "AsyncWebClient",
    stream: Any,
    state: Any,
    run_id: str,
    channel: str,
    thread_ts: str,
    recipient_user_id: Optional[str],
    recipient_team_id: Optional[str],
    task_display_mode: str,
    buffer_size: int,
    requirements: List["RunRequirement"],
    stream_save: Any,
    stream_get: Any,
    post_pause_card: Any,
    paused_event: Any,
    log_prefix: str = "",
) -> None:
    stop_kwargs: Dict[str, Any] = {}
    if state.has_content():
        stop_kwargs["markdown_text"] = state.flush()
    if state.task_cards:
        pending_chunks = state.resolve_all_pending("pending")
        if pending_chunks:
            stop_kwargs["chunks"] = pending_chunks

    try:
        await stream.stop(**stop_kwargs)
    except Exception as exc:
        from agno.os.interfaces.slack.router import _slack_err_code

        log_error(
            f"[HITL] stream.stop on {log_prefix}pause failed: run_id={run_id} "
            f"slack_error={_slack_err_code(exc)!r} | {exc}"
        )

    stream_save(
        run_id,
        LiveStream(
            channel=channel,
            thread_ts=thread_ts,
            recipient_user_id=recipient_user_id,
            recipient_team_id=recipient_team_id,
            task_display_mode=task_display_mode,
            buffer_size=buffer_size,
        ),
    )
    log_info(f"[HITL] {log_prefix}pause saved: run_id={run_id} channel={channel}")

    pause_labels = build_pause_labels(requirements)
    if pause_labels:
        try:
            awaiting_resp = await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="\n".join(pause_labels),
                mrkdwn=True,
            )
            saved_live = stream_get(run_id)
            if saved_live is not None:
                saved_live.awaiting_message_ts = awaiting_resp.get("ts")
        except Exception as exc:
            log_error(f"[HITL] chat_postMessage (awaiting indicator, {log_prefix}pause) failed: {exc}")

    try:
        await post_pause_card(client, paused_event, channel, thread_ts)
    except Exception as exc:
        log_error(f"[HITL] Failed to post Card block ({log_prefix}pause): {exc}")
