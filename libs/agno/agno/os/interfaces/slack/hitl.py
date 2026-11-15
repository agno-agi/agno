from __future__ import annotations

import time
from functools import partial
from typing import Any, Dict, List, Optional, Tuple

from slack_sdk.web.async_client import AsyncWebClient

from agno.agents._hitl import db_call
from agno.os.interfaces.slack.builders import (
    append_submit_if_needed,
    build_admin_approval_status_card,
    response_blocks,
    select_confirmation_row,
)
from agno.os.interfaces.slack.context import EventContext, SlackContext, event_context_from_run
from agno.os.interfaces.slack.executor import (
    APPROVAL_NOT_RECORDED_MESSAGE,
    NO_LONGER_ACTIVE_MESSAGE,
    DecisionRefused,
    cancel_expired_pause,
    continue_run,
    reply_error,
)
from agno.os.interfaces.slack.helpers import (
    delete_awaiting_indicator,
    post_ephemeral,
    resolve_session_id,
    update_message,
)
from agno.os.interfaces.slack.ids import decode_admin_approval_button_value
from agno.os.interfaces.slack.interactions import (
    apply_decisions,
    extract_row_action_context,
    extract_submit_context,
    parse_submit_payload,
    synthetic_submit_payload,
)
from agno.os.interfaces.slack.security import authorize_run, can_act
from agno.os.interfaces.slack.types import ParsedDecision, RowActionContext, SubmitContext
from agno.run.approval import aresolve_approval
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement
from agno.utils.log import log_error, log_info

_NOT_ALLOWED_MESSAGE = "Only the person who started this run or an approver can decide."
_ALREADY_SUBMITTED_MESSAGE = "Already submitted."
_REMOTE_MESSAGE = "This run is paused on a remote AgentOS. Approve it there."


async def _mark_not_resumed(client: AsyncWebClient, channel: str, ts: str, blocks: List[Dict[str, Any]]) -> None:
    notice = {"type": "context", "elements": [{"type": "mrkdwn", "text": "Could not resume this run."}]}
    await update_message(client, channel, ts, "Could not resume", blocks + [notice])


async def _freeze_form(
    client: AsyncWebClient,
    sctx: SubmitContext,
    original_blocks: List[Dict[str, Any]],
    readonly_blocks: List[Dict[str, Any]],
) -> None:
    await delete_awaiting_indicator(client, sctx.channel, sctx.awaiting_ts)
    has_inputs = any(b.get("type") == "input" for b in original_blocks)
    has_interactive_cards = any(b.get("type") == "card" and b.get("actions") for b in original_blocks)
    if has_inputs or has_interactive_cards:
        await update_message(client, sctx.channel, sctx.msg_ts, "Submitted", readonly_blocks)


async def _show_decision(
    client: AsyncWebClient,
    channel: str,
    msg_ts: str,
    awaiting_ts: Optional[str],
    text: str,
    blocks: List[Dict[str, Any]],
) -> None:
    await delete_awaiting_indicator(client, channel, awaiting_ts)
    await update_message(client, channel, msg_ts, text, blocks)


async def _aget_paused_run(ctx: SlackContext, run_id: str, session_id: str) -> Tuple[bool, Optional[Any]]:
    """Whether the stored run was read, and the run while it still waits on a decision, else None."""
    try:
        run_output = await ctx.entity.aget_run_output(run_id=run_id, session_id=session_id)
    except Exception as exc:
        log_error(f"[HITL] aget_run_output failed for run={run_id}: {exc}")
        return False, None
    if run_output is None or getattr(run_output, "status", None) != RunStatus.paused:
        return True, None
    if not getattr(run_output, "active_requirements", None):
        return True, None
    # A native run whose every request expired can no longer be decided, so it ends and its card is frozen
    if await cancel_expired_pause(ctx, run_output):
        return True, None
    return True, run_output


async def _decider_context(
    client: AsyncWebClient,
    ctx: SlackContext,
    *,
    run_id: str,
    channel: str,
    thread_ts: str,
    user: str,
    owner: Optional[str],
    card_ts: str,
    awaiting_ts: Optional[str],
    card_blocks: List[Dict[str, Any]],
    team_id: Optional[str] = None,
) -> Optional[EventContext]:
    """The paused event context of run_id when user may decide on it; posts the ephemeral and returns None otherwise."""
    # Remote entities keep their runs on the remote AgentOS
    if not hasattr(ctx.entity, "aget_run_output"):
        await post_ephemeral(client, channel, user, _REMOTE_MESSAGE, thread_ts)
        return None

    event_context = ctx.runs.find_run(run_id)
    if event_context is None:
        session_id = await resolve_session_id(ctx.entity, ctx.entity_id, channel, thread_ts, ctx.lookup_cache)
        read, run_output = await _aget_paused_run(ctx, run_id, session_id)
        if run_output is None:
            if read:
                # A card whose run no longer waits, e.g. its request expired, is frozen so it is not clicked again
                # Any clicker may freeze it before can_act: its run already ended, so nothing is decided
                await _show_decision(
                    client,
                    channel,
                    card_ts,
                    awaiting_ts,
                    NO_LONGER_ACTIVE_MESSAGE,
                    _update_card_to_no_longer_active(card_blocks),
                )
            await post_ephemeral(client, channel, user, NO_LONGER_ACTIVE_MESSAGE, thread_ts)
            return None
        event_context = await event_context_from_run(
            ctx, run_output, owner=owner, client=client, channel=channel, team_id=team_id
        )

    if not await can_act(ctx, user, event_context, client):
        await post_ephemeral(client, channel, user, _NOT_ALLOWED_MESSAGE, thread_ts)
        return None

    if ctx.users is not None:
        # The owner's authority is checked again on every decision: a disabled or revoked owner's run does not resume
        if not await authorize_run(ctx, event_context, event_context.user_id, client, user, thread_ts):
            return None
    return event_context


async def _decidable_row(
    payload: Dict[str, Any], client: AsyncWebClient, ctx: SlackContext
) -> Optional[RowActionContext]:
    """The clicked row when its user may decide on the run; None otherwise."""
    row = extract_row_action_context(payload)
    if row is None:
        return None
    user = (payload.get("user") or {}).get("id") or ""
    thread_ts = (payload.get("message") or {}).get("thread_ts") or row.card_ts
    event_context = await _decider_context(
        client,
        ctx,
        run_id=row.run_id,
        channel=row.channel,
        thread_ts=thread_ts,
        user=user,
        owner=row.owner,
        card_ts=row.card_ts,
        awaiting_ts=row.awaiting_ts,
        card_blocks=(payload.get("message") or {}).get("blocks") or [],
    )
    if event_context is None:
        return None
    return row


async def _validate_and_apply_decisions(
    client: AsyncWebClient, sctx: SubmitContext, payload: Dict[str, Any], requirements: List[RunRequirement]
) -> Optional[List[ParsedDecision]]:
    decisions, errors = parse_submit_payload(payload, requirements)
    if errors:
        detail = "\n".join(f"* {e.field}: {e.message}" for e in errors)
        await post_ephemeral(
            client, sctx.channel, sctx.user_id, f"Please fix the following and submit again:\n{detail}", sctx.thread_ts
        )
        return None
    apply_decisions(decisions, requirements)
    return decisions


async def _resolve_required_approvals(
    ctx: SlackContext,
    sctx: SubmitContext,
    decisions: List[ParsedDecision],
    requirements: List[RunRequirement],
) -> Optional[str]:
    """Resolve DB approval records for tools with approval_type='required'; the ephemeral to post when one fails."""
    db = getattr(ctx.entity, "db", None)
    if db is None:
        return None

    reqs_by_id = {r.id: r for r in requirements if r.id}
    now = int(time.time())

    for decision in decisions:
        req = reqs_by_id.get(decision.requirement_id)
        tool_exec = getattr(req, "tool_execution", None) if req else None
        if tool_exec is None or getattr(tool_exec, "approval_type", None) != "required":
            continue

        approval_id = getattr(tool_exec, "approval_id", None)
        if approval_id is None:
            continue

        status = "rejected" if decision.approved is False else "approved"
        resolution_data: Dict[str, Any] = {}
        if decision.rejected_note:
            resolution_data["note"] = decision.rejected_note
        if decision.input_values is not None:
            resolution_data["values"] = decision.input_values
        if decision.external_result is not None:
            resolution_data["result"] = decision.external_result
        if decision.feedback_selections is not None:
            resolution_data["feedback"] = decision.feedback_selections

        resolved = await aresolve_approval(
            db,
            approval_id,
            status=status,
            resolved_by=sctx.user_id,
            resolved_at=now,
            resolution_data=resolution_data or None,
        )
        if resolved is None:
            # Already resolved (an earlier partial submit, or an admin in AgentOS): fine when it says the same
            existing_status = (await _aget_approval(ctx, approval_id) or {}).get("status")
            if existing_status in (None, "pending"):
                return APPROVAL_NOT_RECORDED_MESSAGE
            if existing_status != status:
                return NO_LONGER_ACTIVE_MESSAGE
    return None


async def _record_approvals(
    ctx: SlackContext, sctx: SubmitContext, decisions: List[ParsedDecision], requirements: List[RunRequirement]
) -> None:
    """Record the approvals before anything resumes the run; a continue refused earlier leaves them pending."""
    refusal = await _resolve_required_approvals(ctx, sctx, decisions, requirements)
    if refusal is not None:
        raise DecisionRefused(refusal)


async def _aget_approval(ctx: SlackContext, approval_id: str) -> Optional[Dict[str, Any]]:
    """The approval row from DB, or None."""
    db = getattr(ctx.entity, "db", None)
    if db is None or not approval_id:
        return None
    try:
        return await db_call(db, "get_approval", approval_id)
    except Exception as exc:
        log_error(f"[HITL] Failed to get approval status: {exc}")
        return None


def _update_card_to_approved(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Update approval card blocks to show approved status."""
    new_blocks = []
    for block in blocks:
        if block.get("type") == "card" and "admin_approval" in block.get("block_id", ""):
            block = dict(block)
            block["subtext"] = {"type": "mrkdwn", "text": ":white_check_mark: Approved"}
            block["actions"] = []
        new_blocks.append(block)
    return new_blocks


def _update_card_to_no_longer_active(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Update approval card blocks to show the approval is no longer active."""
    new_blocks = []
    for block in blocks:
        if block.get("type") == "actions":
            continue
        if block.get("type") == "card":
            block = dict(block)
            block["subtext"] = {"type": "mrkdwn", "text": NO_LONGER_ACTIVE_MESSAGE}
            block["actions"] = []
        new_blocks.append(block)
    return new_blocks


def _replace_admin_card(blocks: List[Dict[str, Any]], card: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        card if block.get("type") == "card" and "admin_approval" in block.get("block_id", "") else block
        for block in blocks
    ]


async def handle_row_approve(payload: Dict[str, Any], client: AsyncWebClient, ctx: SlackContext) -> None:
    row = await _decidable_row(payload, client, ctx)
    if row is None:
        return

    result = select_confirmation_row(row, selected="approve", include_reason_input=False)
    await update_message(client, row.channel, row.card_ts, "Approval pending", result.blocks)

    if result.should_auto_submit:
        await handle_submit(
            synthetic_submit_payload(payload, row.run_id, row.awaiting_ts, result.blocks, row.owner), client, ctx
        )


async def handle_row_reject(payload: Dict[str, Any], client: AsyncWebClient, ctx: SlackContext) -> None:
    row = await _decidable_row(payload, client, ctx)
    if row is None:
        return

    result = select_confirmation_row(row, selected="deny", include_reason_input=True)
    blocks = append_submit_if_needed(result.blocks, row.run_id, row.awaiting_ts, row.owner)
    await update_message(client, row.channel, row.card_ts, "Rejection pending", blocks)


async def handle_submit(payload: Dict[str, Any], client: AsyncWebClient, ctx: SlackContext) -> None:
    sctx = extract_submit_context(payload)
    if sctx is None:
        return
    log_info(f"[HITL] submit received: run_id={sctx.run_id} channel={sctx.channel}")
    original_blocks = list((payload.get("message") or {}).get("blocks") or [])

    event_context = await _decider_context(
        client,
        ctx,
        run_id=sctx.run_id,
        channel=sctx.channel,
        thread_ts=sctx.thread_ts,
        user=sctx.user_id,
        owner=sctx.owner,
        card_ts=sctx.msg_ts,
        awaiting_ts=sctx.awaiting_ts,
        card_blocks=original_blocks,
        team_id=sctx.team_id,
    )
    if event_context is None:
        return

    # One continuation per run: a double click or a second approver gets an ephemeral, never a second run
    if not ctx.runs.claim_run(sctx.run_id):
        await post_ephemeral(client, sctx.channel, sctx.user_id, _ALREADY_SUBMITTED_MESSAGE, sctx.thread_ts)
        return
    try:
        # Re-read after the claim: an earlier submit may have continued the run since the first read
        read, run_output = await _aget_paused_run(ctx, sctx.run_id, event_context.session_id)
        if run_output is None:
            if read:
                await _show_decision(
                    client,
                    sctx.channel,
                    sctx.msg_ts,
                    sctx.awaiting_ts,
                    NO_LONGER_ACTIVE_MESSAGE,
                    _update_card_to_no_longer_active(original_blocks),
                )
            await post_ephemeral(client, sctx.channel, sctx.user_id, NO_LONGER_ACTIVE_MESSAGE, sctx.thread_ts)
            return
        requirements = list(run_output.active_requirements)

        decisions = await _validate_and_apply_decisions(client, sctx, payload, requirements)
        if decisions is None:
            return

        readonly_blocks = response_blocks(original_blocks, sctx.state_values, requirements)

        try:
            resumed = await continue_run(
                event_context,
                client,
                ctx,
                requirements,
                decisions=decisions,
                before_continue=partial(_record_approvals, ctx, sctx, decisions, requirements),
                on_accepted=partial(_freeze_form, client, sctx, original_blocks, readonly_blocks),
                clicker=sctx.user_id,
            )
        except DecisionRefused as exc:
            # The card stays live: the decision never reached the run
            await post_ephemeral(
                client, sctx.channel, sctx.user_id, str(exc) or NO_LONGER_ACTIVE_MESSAGE, sctx.thread_ts
            )
            return
        except Exception as e:
            log_error(f"[HITL] continuation failed for run={sctx.run_id}: {e}")
            await _mark_not_resumed(client, sctx.channel, sctx.msg_ts, readonly_blocks)
            await reply_error(e, event_context, client, ctx)
            return
        if not resumed:
            await _mark_not_resumed(client, sctx.channel, sctx.msg_ts, readonly_blocks)
    finally:
        ctx.runs.release_run(sctx.run_id)


async def handle_check_status(payload: Dict[str, Any], client: AsyncWebClient, ctx: SlackContext) -> None:
    """Handle 'Check Status' button click for admin approval cards."""
    # 1. Parse button value
    actions = payload.get("actions") or []
    if not actions:
        return
    button_value = actions[0].get("value") or ""
    approval_id, req_id, run_id, awaiting_ts, owner = decode_admin_approval_button_value(button_value)
    if not approval_id or not req_id or not run_id:
        log_error(f"[HITL] Invalid admin approval button value: {button_value!r}")
        return

    # 2. Extract Slack context
    channel = (payload.get("channel") or {}).get("id", "")
    message = payload.get("message") or {}
    msg_ts = message.get("ts", "")
    thread_ts = message.get("thread_ts") or msg_ts
    user = (payload.get("user") or {}).get("id") or ""
    if not channel or not msg_ts or not thread_ts:
        log_error(f"[HITL] Missing Slack context: channel={channel}, msg_ts={msg_ts}, thread_ts={thread_ts}")
        return

    event_context = await _decider_context(
        client,
        ctx,
        run_id=run_id,
        channel=channel,
        thread_ts=thread_ts,
        user=user,
        owner=owner,
        card_ts=msg_ts,
        awaiting_ts=awaiting_ts,
        card_blocks=message.get("blocks", []),
        team_id=(payload.get("team") or {}).get("id"),
    )
    if event_context is None:
        return

    # 3. Extract card info for rebuilding
    blocks = message.get("blocks", [])
    tool_name_str = "Tool"
    body_text = ""
    for block in blocks:
        if block.get("type") == "card":
            tool_name_str = (block.get("title", {}).get("text") or "Tool").strip("*")
            body_text = block.get("body", {}).get("text") or ""
            break

    # 4. Query approval status
    approval = await _aget_approval(ctx, approval_id)
    status = (approval or {}).get("status", "pending")
    card = build_admin_approval_status_card(
        tool_name=tool_name_str,
        body_text=body_text,
        status=status,
        req_id=req_id,
        approval_id=approval_id,
        run_id=run_id,
        awaiting_ts=awaiting_ts,
        owner=owner,
    )

    # 5. Still pending: refresh the card, keeping the indicator ts as it was
    if status not in ("approved", "rejected"):
        await update_message(client, channel, msg_ts, f"Status: {status}", _replace_admin_card(blocks, card.to_dict()))
        return

    # 6. Decided by the admin: continue the run either way, so a rejection does not leave it paused
    if not ctx.runs.claim_run(run_id):
        await post_ephemeral(client, channel, user, _ALREADY_SUBMITTED_MESSAGE, thread_ts)
        return
    try:
        read, run_output = await _aget_paused_run(ctx, run_id, event_context.session_id)
        if run_output is None:
            if read:
                await _show_decision(
                    client,
                    channel,
                    msg_ts,
                    awaiting_ts,
                    NO_LONGER_ACTIVE_MESSAGE,
                    _update_card_to_no_longer_active(blocks),
                )
            await post_ephemeral(client, channel, user, NO_LONGER_ACTIVE_MESSAGE, thread_ts)
            return
        requirements = list(run_output.active_requirements)
        decided = next(
            (r for r in requirements if r.tool_execution and r.tool_execution.approval_id == approval_id), None
        )
        if decided is None:
            # The run waits on something else now; continuing would leave this approval unresolved
            await post_ephemeral(client, channel, user, NO_LONGER_ACTIVE_MESSAGE, thread_ts)
            return
        if status == "approved":
            decided.confirm()
            decided_text, decided_blocks = "Approved", _update_card_to_approved(blocks)
        else:
            decided.reject(((approval or {}).get("resolution_data") or {}).get("note"))
            decided_text, decided_blocks = "Status: rejected", _replace_admin_card(blocks, card.to_dict())

        try:
            resumed = await continue_run(
                event_context,
                client,
                ctx,
                requirements,
                on_accepted=partial(_show_decision, client, channel, msg_ts, awaiting_ts, decided_text, decided_blocks),
                clicker=user,
            )
        except DecisionRefused as exc:
            await post_ephemeral(client, channel, user, str(exc) or NO_LONGER_ACTIVE_MESSAGE, thread_ts)
            return
        except Exception as e:
            log_error(f"[HITL] continuation failed for run={run_id}: {e}")
            await _mark_not_resumed(client, channel, msg_ts, decided_blocks)
            await reply_error(e, event_context, client, ctx)
            return
        if not resumed:
            await _mark_not_resumed(client, channel, msg_ts, decided_blocks)
    finally:
        ctx.runs.release_run(run_id)
