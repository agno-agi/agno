from __future__ import annotations

from dataclasses import dataclass
from ssl import SSLContext
from typing import Any, Dict, List, Literal, Optional, Union

from slack_sdk.web.async_client import AsyncWebClient

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.slack.builders import (
    append_submit_if_needed,
    response_blocks,
    select_confirmation_row,
)
from agno.os.interfaces.slack.events import process_event
from agno.os.interfaces.slack.helpers import open_chat_stream, slack_error_code
from agno.os.interfaces.slack.interactions import (
    apply_decisions,
    extract_row_action_context,
    extract_submit_context,
    parse_submit_payload,
    synthetic_submit_payload,
)
from agno.os.interfaces.slack.state import StreamState, TaskStatus
from agno.os.interfaces.slack.types import SubmitContext, tool_args, tool_name, truncate
from agno.team import RemoteTeam, Team
from agno.tools.slack import SlackTools
from agno.utils.log import log_error, log_info
from agno.workflow import RemoteWorkflow, Workflow

_STREAM_CHAR_LIMIT = 3900


@dataclass
class HITLHandler:
    slack_tools: SlackTools
    ssl: Optional[SSLContext]
    entity: Union[Agent, RemoteAgent, Team, RemoteTeam, Workflow, RemoteWorkflow]
    entity_id: str
    entity_name: str
    entity_type: Literal["agent", "team", "workflow"]
    task_display_mode: str
    buffer_size: int

    def _client(self) -> AsyncWebClient:
        return AsyncWebClient(token=self.slack_tools.token, ssl=self.ssl)

    async def update_message(
        self,
        channel: str,
        ts: str,
        text: str,
        blocks: List[Dict[str, Any]],
    ) -> bool:
        try:
            await self._client().chat_update(channel=channel, ts=ts, text=text, blocks=blocks)
            return True
        except Exception as exc:
            log_error(f"[HITL] chat_update failed for ts={ts}: {exc}")
            return False

    async def delete_awaiting_indicator(self, channel: str, awaiting_ts: Optional[str]) -> None:
        if not awaiting_ts:
            return
        try:
            await self._client().chat_delete(channel=channel, ts=awaiting_ts)
        except Exception as exc:
            if "message_not_found" not in str(exc):
                log_error(f"[HITL] chat_delete (awaiting indicator) failed for ts={awaiting_ts}: {exc}")

    async def load_active_requirements(self, ctx: SubmitContext) -> List[Any]:
        try:
            run_output = await self.entity.aget_run_output(run_id=ctx.run_id, session_id=ctx.session_id)  # type: ignore[union-attr]
        except Exception as exc:
            log_error(f"[HITL] aget_run_output failed for run={ctx.run_id}: {exc}")
            return []
        return list(getattr(run_output, "active_requirements", None) or []) if run_output else []

    async def freeze_form(
        self, ctx: SubmitContext, original_blocks: List[Dict[str, Any]], requirements: List[Any]
    ) -> None:
        has_inputs = any(b.get("type") == "input" for b in original_blocks)
        has_interactive_cards = any(b.get("type") == "card" and b.get("actions") for b in original_blocks)
        if not has_inputs and not has_interactive_cards:
            return

        readonly_blocks = response_blocks(original_blocks, ctx.state_values, requirements)
        try:
            await self._client().chat_update(
                channel=ctx.channel, ts=ctx.msg_ts, text="Submitted", blocks=readonly_blocks
            )
        except Exception as exc:
            log_error(f"[HITL] chat_update (submit readonly) failed for {ctx.msg_ts}: {exc}")

    async def validate_and_apply_decisions(
        self,
        ctx: SubmitContext,
        payload: Dict[str, Any],
        requirements: List[Any],
    ) -> Optional[List[Any]]:
        decisions, errors = parse_submit_payload(payload, requirements)
        if errors:
            detail = "\n".join(f"* {e.field}: {e.message}" for e in errors)
            await self.post_ephemeral(
                channel=ctx.channel, user=ctx.user_id, text=f"Please fix the following and submit again:\n{detail}"
            )
            return None
        apply_decisions(decisions, requirements)
        return decisions

    async def post_denial_cards(self, stream: Any, decisions: List[Any], requirements: List[Any], run_id: str) -> None:
        requirements_by_id = {r.id: r for r in requirements if r.id}
        for decision in decisions:
            req = requirements_by_id.get(decision.requirement_id)
            if req is None or decision.pause_type != "confirmation" or decision.approved is True:
                continue
            name = tool_name(req)
            args_dict = tool_args(req)
            arg_parts = [f"{k}={truncate(str(v), 40)}" for k, v in args_dict.items()]
            args_str = ", ".join(arg_parts)
            title = truncate(f"Denied: {name}({args_str})" if args_str else f"Denied: {name}", 120)
            try:
                await stream.append(
                    markdown_text="",
                    chunks=[
                        {
                            "type": "task_update",
                            "id": f"approval:{decision.requirement_id}",
                            "title": title,
                            "status": "complete",
                        }
                    ],
                )
            except Exception as exc:
                log_error(
                    f"[HITL] decision_update append failed: run_id={run_id} slack_error={slack_error_code(exc)!r} | {exc}"
                )

    async def stream_resumed_run(
        self,
        ctx: SubmitContext,
        stream: Any,
        requirements: List[Any],
    ) -> StreamState:
        state = StreamState(entity_name=self.entity_name, entity_type=self.entity_type)
        try:
            response_stream: Any = self.entity.acontinue_run(  # type: ignore[union-attr, call-arg, call-overload]
                run_id=ctx.run_id,
                requirements=requirements,
                session_id=ctx.session_id,
                stream=True,
                stream_events=True,
            )
        except Exception as exc:
            log_error(f"[HITL] acontinue_run (stream) failed for run={ctx.run_id}: {exc}")
            return state

        try:
            async for chunk in response_stream:
                state.collect_media(chunk)
                ev = getattr(chunk, "event", None)
                if ev and await process_event(ev, chunk, state, stream):
                    break
                if state.has_content():
                    content = state.flush()
                    if content and state.stream_chars_sent + len(content) <= _STREAM_CHAR_LIMIT:
                        await stream.append(markdown_text=content)
                        state.stream_chars_sent += len(content)
        except Exception as exc:
            log_error(
                f"[HITL] continuation append failed: run_id={ctx.run_id} slack_error={slack_error_code(exc)!r} | {exc}"
            )
        return state

    async def complete_or_repause(
        self,
        ctx: SubmitContext,
        stream: Any,
        state: StreamState,
    ) -> None:
        if state.paused_event is not None:
            requirements = list(getattr(state.paused_event, "active_requirements", None) or [])
            if requirements:
                from agno.os.interfaces.slack.pause import finalize_pause, post_pause_card

                new_awaiting_ts = await finalize_pause(
                    client=self._client(),
                    stream=stream,
                    state=state,
                    run_id=ctx.run_id,
                    channel=ctx.channel,
                    thread_ts=ctx.thread_ts,
                    requirements=requirements,
                    log_prefix="re-",
                )
                try:
                    await post_pause_card(
                        self._client(), state.paused_event, ctx.channel, ctx.thread_ts, new_awaiting_ts
                    )
                except Exception as exc:
                    log_error(f"[HITL] Failed to post Card block (re-pause): {exc}")
                return

        stop_kwargs: Dict[str, Any] = {}
        if state.has_content():
            stop_kwargs["markdown_text"] = state.flush()
        if state.task_cards:
            final_status: TaskStatus = state.terminal_status or "complete"
            completion_chunks = state.resolve_all_pending(final_status)
            if completion_chunks:
                stop_kwargs["chunks"] = completion_chunks
        try:
            await stream.stop(**stop_kwargs)
        except Exception as exc:
            log_error(
                f"[HITL] stream.stop after resume failed: run_id={ctx.run_id} slack_error={slack_error_code(exc)!r} | {exc}"
            )

    async def handle_row_approve(self, payload: Dict[str, Any]) -> None:
        ctx = extract_row_action_context(payload)
        if ctx is None:
            return

        result = select_confirmation_row(ctx, selected="approve", include_reason_input=False)
        await self.update_message(ctx.channel, ctx.card_ts, "Approval pending", result.blocks)

        if result.should_auto_submit:
            await self.handle_submit(synthetic_submit_payload(payload, ctx.run_id, ctx.awaiting_ts, result.blocks))

    async def handle_row_reject(self, payload: Dict[str, Any]) -> None:
        ctx = extract_row_action_context(payload)
        if ctx is None:
            return

        result = select_confirmation_row(ctx, selected="deny", include_reason_input=True)
        blocks = append_submit_if_needed(result.blocks, ctx.run_id, ctx.awaiting_ts)
        await self.update_message(ctx.channel, ctx.card_ts, "Rejection pending", blocks)

    async def handle_submit(self, payload: Dict[str, Any]) -> None:
        ctx = extract_submit_context(payload, self.entity_id)
        if ctx is None:
            return
        log_info(f"[HITL] submit received: run_id={ctx.run_id} channel={ctx.channel}")

        await self.delete_awaiting_indicator(ctx.channel, ctx.awaiting_ts)

        requirements = await self.load_active_requirements(ctx)
        if not requirements:
            await self.post_ephemeral(channel=ctx.channel, user=ctx.user_id, text="This approval is no longer active.")
            return

        decisions = await self.validate_and_apply_decisions(ctx, payload, requirements)
        if decisions is None:
            return

        original_blocks = list((payload.get("message") or {}).get("blocks") or [])
        await self.freeze_form(ctx, original_blocks, requirements)

        stream = await open_chat_stream(
            self._client(), ctx.channel, ctx.thread_ts, ctx.user_id, ctx.team_id,
            self.task_display_mode, self.buffer_size,
        )

        await self.post_denial_cards(stream, decisions, requirements, ctx.run_id)
        state = await self.stream_resumed_run(ctx, stream, requirements)
        await self.complete_or_repause(ctx, stream, state)

    async def post_ephemeral(self, *, channel: str, user: str, text: str) -> None:
        try:
            await self._client().chat_postEphemeral(channel=channel, user=user, text=text)
        except Exception as exc:
            log_error(f"[HITL] chat_postEphemeral failed: {exc}")
