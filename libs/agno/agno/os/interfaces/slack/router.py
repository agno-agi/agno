from dataclasses import dataclass
from ssl import SSLContext
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.slack.helpers import (
    download_event_files,
    extract_event_context,
    member_name,
    send_slack_message,
    should_respond,
    task_id,
    upload_response_media,
)
from agno.os.interfaces.slack.security import verify_slack_signature
from agno.os.interfaces.slack.state import StreamState
from agno.team import RemoteTeam, Team
from agno.tools.slack import SlackTools
from agno.utils.log import log_error
from agno.workflow import RemoteWorkflow, Workflow

# Slack sends lifecycle events for bots with these subtypes. Without this
# filter the router would try to process its own messages, causing infinite loops.
_IGNORED_SUBTYPES = frozenset(
    {
        "bot_message",
        "bot_add",
        "bot_remove",
        "bot_enable",
        "bot_disable",
        "message_changed",
        "message_deleted",
    }
)


def _normalize_event(event: str) -> str:
    # Strip "Team" prefix so agent events ("ToolCallStarted") and team events
    # ("TeamToolCallStarted") are handled by the same if/elif branches.
    return event[4:] if event.startswith("Team") else event


@dataclass(frozen=True)
class _ToolRef:
    tid: str | None
    label: str
    errored: bool


def _extract_tool_ref(chunk: Any, state: StreamState, *, fallback_id: str | None = None) -> _ToolRef:
    tool = getattr(chunk, "tool", None)
    tool_name = (tool.tool_name if tool else None) or "tool"
    call_id = (tool.tool_call_id if tool else None) or fallback_id
    member = member_name(chunk, state.entity_name)
    label = f"{member}: {tool_name}" if member else tool_name
    tid = task_id(member, call_id) if call_id else None  # type: ignore[arg-type]
    errored = bool(tool.tool_call_error) if tool else False
    return _ToolRef(tid=tid, label=label, errored=errored)


async def _emit_task(
    stream: Any,
    task_id: str,
    title: str,
    status: str,
    *,
    output: str | None = None,
) -> None:
    chunk: dict = {"type": "task_update", "id": task_id, "title": title, "status": status}
    if output:
        chunk["output"] = output[:200]  # Slack truncates longer task output
    await stream.append(chunks=[chunk])


async def _wf_task(
    chunk: Any,
    state: StreamState,
    stream: Any,
    prefix: str,
    label: str = "",
    *,
    started: bool,
    name_attr: str = "step_name",
) -> None:
    name = getattr(chunk, name_attr, None) or prefix
    sid = getattr(chunk, "step_id", None) or name
    key = f"wf_{prefix}_{sid}"
    title = f"{label}: {name}" if label else name
    if started:
        state.track_task(key, title)
        await _emit_task(stream, key, title, "in_progress")
    else:
        state.complete_task(key)
        await _emit_task(stream, key, title, "complete")


# Workflows orchestrate multiple agents via steps/loops/conditions. Without
# suppression, each inner agent's tool calls and reasoning events would flood
# the Slack stream with low-level noise. We only show step-level progress.
# Values are NORMALIZED (no "Team" prefix) so one set covers agent + team events.
_SUPPRESSED_IN_WORKFLOW: frozenset[str] = frozenset(
    {
        "ReasoningStarted",
        "ReasoningCompleted",
        "ToolCallStarted",
        "ToolCallCompleted",
        "ToolCallError",
        "MemoryUpdateStarted",
        "MemoryUpdateCompleted",
        "RunContent",
        "RunIntermediateContent",
        "RunCompleted",
        "RunError",
        "RunCancelled",
    }
)


async def _process_event(ev_raw: str, chunk: Any, state: StreamState, stream: Any) -> bool:
    # Returns True on terminal events (error/cancel) to break the stream loop.
    ev = _normalize_event(ev_raw)
    is_workflow = state.entity_type == "workflow"

    # Workflow mode: suppress nested agent internals
    if is_workflow and ev in _SUPPRESSED_IN_WORKFLOW:
        return False

    # --- Reasoning ---
    if ev == "ReasoningStarted":
        key = f"reasoning_{state.reasoning_round}"
        state.track_task(key, "Reasoning")
        await _emit_task(stream, key, "Reasoning", "in_progress")

    elif ev == "ReasoningCompleted":
        key = f"reasoning_{state.reasoning_round}"
        state.complete_task(key)
        state.reasoning_round += 1
        await _emit_task(stream, key, "Reasoning", "complete")

    # --- Tools ---
    elif ev == "ToolCallStarted":
        ref = _extract_tool_ref(chunk, state, fallback_id=str(len(state.task_cards)))
        if ref.tid:
            state.track_task(ref.tid, ref.label)
            await _emit_task(stream, ref.tid, ref.label, "in_progress")

    elif ev == "ToolCallCompleted":
        ref = _extract_tool_ref(chunk, state)
        if ref.tid:
            if ref.tid not in state.task_cards:
                state.track_task(ref.tid, ref.label)
            if ref.errored:
                state.error_task(ref.tid)
            else:
                state.complete_task(ref.tid)
            await _emit_task(stream, ref.tid, ref.label, "error" if ref.errored else "complete")

    elif ev == "ToolCallError":
        ref = _extract_tool_ref(chunk, state, fallback_id=f"tool_error_{state.error_count}")
        error_msg = getattr(chunk, "error", None) or "Tool call failed"
        state.error_count += 1
        if ref.tid:
            if ref.tid in state.task_cards:
                state.error_task(ref.tid)
            else:
                state.track_task(ref.tid, ref.label)
                state.error_task(ref.tid)
            await _emit_task(stream, ref.tid, ref.label, "error", output=str(error_msg))

    # --- Content ---
    elif ev == "RunContent":
        content = getattr(chunk, "content", None)
        if content is not None:
            state.text_buffer += str(content)

    elif ev == "RunIntermediateContent":
        # Teams emit intermediate content from each member as they finish. Showing
        # these would interleave partial outputs in the stream. The team leader
        # emits a single consolidated RunContent at the end — that's what we show.
        if state.entity_type != "team":
            content = getattr(chunk, "content", None)
            if content is not None:
                state.text_buffer += str(content)

    # --- Memory ---
    elif ev == "MemoryUpdateStarted":
        state.track_task("memory_update", "Updating memory")
        await _emit_task(stream, "memory_update", "Updating memory", "in_progress")

    elif ev == "MemoryUpdateCompleted":
        state.complete_task("memory_update")
        await _emit_task(stream, "memory_update", "Updating memory", "complete")

    # --- Run lifecycle ---
    elif ev == "RunCompleted":
        pass  # Finalization handled by caller after stream ends

    elif ev in ("RunError", "RunCancelled"):
        state.error_count += 1
        error_msg = getattr(chunk, "content", None) or "An error occurred"
        state.text_buffer += f"\n_Error: {error_msg}_"
        state.terminal_status = "error"
        return True

    # --- Workflow step output (behavior differs by mode) ---
    elif ev_raw == "StepOutput":
        content = getattr(chunk, "content", None)
        if content is not None:
            if is_workflow:
                # Workflow steps may produce intermediate output before the final
                # WorkflowCompleted event. We capture (not stream) it here so the
                # completed handler can use it as a fallback if chunk.content is None.
                state.workflow_final_content = str(content)
            else:
                state.text_buffer += str(content)

    # --- Workflow lifecycle ---
    elif ev_raw == "WorkflowStarted":
        wf_name = getattr(chunk, "workflow_name", None) or state.entity_name or "Workflow"
        run_id = getattr(chunk, "run_id", None) or "run"
        key = f"wf_run_{run_id}"
        state.track_task(key, f"Workflow: {wf_name}")
        await _emit_task(stream, key, f"Workflow: {wf_name}", "in_progress")

    elif ev_raw == "WorkflowCompleted":
        run_id = getattr(chunk, "run_id", None) or "run"
        wf_name = getattr(chunk, "workflow_name", None) or state.entity_name or "Workflow"
        key = f"wf_run_{run_id}"
        state.complete_task(key)
        await _emit_task(stream, key, f"Workflow: {wf_name}", "complete")
        final = getattr(chunk, "content", None)
        if final is None:
            final = state.workflow_final_content
        if final:
            state.text_buffer += str(final)

    elif ev_raw in ("WorkflowError", "WorkflowCancelled"):
        state.error_count += 1
        error_msg = getattr(chunk, "error", None) or getattr(chunk, "content", None) or "Workflow failed"
        state.text_buffer += f"\n_Error: {error_msg}_"
        state.terminal_status = "error"
        return True

    # --- Workflow structural events ---
    elif ev_raw == "StepStarted":
        await _wf_task(chunk, state, stream, "step", started=True)
    elif ev_raw == "StepCompleted":
        await _wf_task(chunk, state, stream, "step", started=False)
    elif ev_raw == "StepError":
        step_name = getattr(chunk, "step_name", None) or "step"
        sid = getattr(chunk, "step_id", None) or step_name
        key = f"wf_step_{sid}"
        error_msg = getattr(chunk, "error", None) or "Step failed"
        state.error_task(key)
        await _emit_task(stream, key, step_name, "error", output=str(error_msg))

    # --- Workflow loops (explicit — titles include iteration/max info) ---
    elif ev_raw == "LoopExecutionStarted":
        step_name = getattr(chunk, "step_name", None) or "loop"
        loop_key = getattr(chunk, "step_id", None) or step_name
        max_iter = getattr(chunk, "max_iterations", None)
        title = f"Loop: {step_name}" + (f" (max {max_iter})" if max_iter else "")
        key = f"wf_loop_{loop_key}"
        state.track_task(key, title)
        await _emit_task(stream, key, title, "in_progress")

    elif ev_raw == "LoopIterationStarted":
        loop_key = getattr(chunk, "step_id", None) or getattr(chunk, "step_name", None) or "loop"
        iteration = getattr(chunk, "iteration", 0)
        max_iter = getattr(chunk, "max_iterations", None)
        title = f"Iteration {iteration}" + (f"/{max_iter}" if max_iter else "")
        key = f"wf_loop_{loop_key}_iter_{iteration}"
        state.track_task(key, title)
        await _emit_task(stream, key, title, "in_progress")

    elif ev_raw == "LoopIterationCompleted":
        loop_key = getattr(chunk, "step_id", None) or getattr(chunk, "step_name", None) or "loop"
        iteration = getattr(chunk, "iteration", 0)
        key = f"wf_loop_{loop_key}_iter_{iteration}"
        state.complete_task(key)
        await _emit_task(stream, key, f"Iteration {iteration}", "complete")

    elif ev_raw == "LoopExecutionCompleted":
        step_name = getattr(chunk, "step_name", None) or "loop"
        loop_key = getattr(chunk, "step_id", None) or step_name
        key = f"wf_loop_{loop_key}"
        state.complete_task(key)
        await _emit_task(stream, key, f"Loop: {step_name}", "complete")

    # --- Workflow parallel / conditions / routing / agent / steps ---
    elif ev_raw == "ParallelExecutionStarted":
        await _wf_task(chunk, state, stream, "parallel", "Parallel", started=True)
    elif ev_raw == "ParallelExecutionCompleted":
        await _wf_task(chunk, state, stream, "parallel", "Parallel", started=False)
    elif ev_raw == "ConditionExecutionStarted":
        await _wf_task(chunk, state, stream, "cond", "Condition", started=True)
    elif ev_raw == "ConditionExecutionCompleted":
        await _wf_task(chunk, state, stream, "cond", "Condition", started=False)
    elif ev_raw == "RouterExecutionStarted":
        await _wf_task(chunk, state, stream, "router", "Router", started=True)
    elif ev_raw == "RouterExecutionCompleted":
        await _wf_task(chunk, state, stream, "router", "Router", started=False)
    elif ev_raw == "WorkflowAgentStarted":
        await _wf_task(chunk, state, stream, "agent", "Running", started=True, name_attr="agent_name")
    elif ev_raw == "WorkflowAgentCompleted":
        await _wf_task(chunk, state, stream, "agent", "Running", started=False, name_attr="agent_name")
    elif ev_raw == "StepsExecutionStarted":
        await _wf_task(chunk, state, stream, "steps", "Steps", started=True)
    elif ev_raw == "StepsExecutionCompleted":
        await _wf_task(chunk, state, stream, "steps", "Steps", started=False)

    return False


class SlackEventResponse(BaseModel):
    status: str = Field(default="ok")


class SlackChallengeResponse(BaseModel):
    challenge: str = Field(description="Challenge string to echo back to Slack")


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    reply_to_mentions_only: bool = True,
    token: Optional[str] = None,
    signing_secret: Optional[str] = None,
    streaming: bool = False,
    loading_messages: Optional[List[str]] = None,
    task_display_mode: str = "plan",
    loading_text: str = "Thinking...",
    suggested_prompts: Optional[List[Dict[str, str]]] = None,
    ssl: Optional[SSLContext] = None,
    buffer_size: int = 100,
) -> APIRouter:
    entity = agent or team or workflow
    entity_type = "agent" if agent else "team" if team else "workflow" if workflow else "unknown"
    raw_name = getattr(entity, "name", None)
    entity_name = raw_name if isinstance(raw_name, str) else entity_type
    # Multiple Slack instances can be mounted on one FastAPI app (e.g. /research
    # and /analyst). op_suffix makes each operation_id unique to avoid collisions.
    op_suffix = entity_name.lower().replace(" ", "_")

    slack_tools = SlackTools(token=token, ssl=ssl)

    @router.post(
        "/events",
        operation_id=f"slack_events_{op_suffix}",
        name="slack_events",
        description="Process incoming Slack events",
        response_model=Union[SlackChallengeResponse, SlackEventResponse],
        response_model_exclude_none=True,
        responses={
            200: {"description": "Event processed successfully"},
            400: {"description": "Missing Slack headers"},
            403: {"description": "Invalid Slack signature"},
        },
    )
    async def slack_events(request: Request, background_tasks: BackgroundTasks):
        # ACK immediately, process in background. Slack retries after ~3s if it
        # doesn't get a 200, so long-running agent calls must not block the response.
        body = await request.body()
        timestamp = request.headers.get("X-Slack-Request-Timestamp")
        slack_signature = request.headers.get("X-Slack-Signature", "")

        if not timestamp or not slack_signature:
            raise HTTPException(status_code=400, detail="Missing Slack headers")

        if not verify_slack_signature(body, timestamp, slack_signature, signing_secret=signing_secret):
            raise HTTPException(status_code=403, detail="Invalid signature")

        # Slack retries after ~3s if it doesn't get a 200. Since we ACK
        # immediately and process in background, retries are always duplicates.
        # Trade-off: if the server crashes mid-processing, the retried event
        # carrying the same payload won't be reprocessed — acceptable for chat.
        if request.headers.get("X-Slack-Retry-Num"):
            return SlackEventResponse(status="ok")

        data = await request.json()

        if data.get("type") == "url_verification":
            return SlackChallengeResponse(challenge=data.get("challenge"))

        if "event" in data:
            event = data["event"]
            event_type = event.get("type")
            if event_type == "assistant_thread_started" and streaming:
                background_tasks.add_task(_handle_thread_started, event)
            # Bot self-loop prevention: check bot_id at both the top-level event
            # and inside message_changed's nested "message" object. Without the
            # nested check, edited bot messages would be reprocessed as new events.
            elif (
                event.get("bot_id")
                or (event.get("message") or {}).get("bot_id")
                or event.get("subtype") in _IGNORED_SUBTYPES
            ):
                pass
            elif streaming:
                background_tasks.add_task(_stream_slack_response, data)
            else:
                background_tasks.add_task(_process_slack_event, event)

        return SlackEventResponse(status="ok")

    async def _process_slack_event(event: dict):
        if not should_respond(event, reply_to_mentions_only):
            return

        ctx = extract_event_context(event)

        # Show typing indicator immediately so the user knows the bot received their message.
        try:
            from slack_sdk.web.async_client import AsyncWebClient

            async_client = AsyncWebClient(token=slack_tools.token, ssl=ssl)
            await async_client.assistant_threads_setStatus(
                channel_id=ctx["channel_id"],
                thread_ts=ctx["thread_id"],
                status="Thinking...",
            )
        except Exception:
            pass

        files, images, videos, audio = download_event_files(slack_tools, event)

        run_kwargs: Dict[str, Any] = {
            "user_id": ctx["user"],
            "session_id": ctx["thread_id"],
            "files": files if files else None,
            "images": images if images else None,
            "videos": videos if videos else None,
            "audio": audio if audio else None,
        }

        try:
            response = None
            if agent:
                response = await agent.arun(ctx["message_text"], **run_kwargs)  # type: ignore[misc]
            elif team:
                response = await team.arun(ctx["message_text"], **run_kwargs)  # type: ignore
            elif workflow:
                response = await workflow.arun(ctx["message_text"], **run_kwargs)  # type: ignore

            if response:
                if response.status == "ERROR":
                    log_error(f"Error processing message: {response.content}")
                    send_slack_message(
                        slack_tools,
                        channel=ctx["channel_id"],
                        message="Sorry, there was an error processing your message. Please try again later.",
                        thread_ts=ctx["thread_id"],
                    )
                    return

                if hasattr(response, "reasoning_content") and response.reasoning_content:
                    rc = str(response.reasoning_content)
                    formatted = f"*Reasoning:*\n> {rc.replace(chr(10), chr(10) + '> ')}"
                    send_slack_message(
                        slack_tools, channel=ctx["channel_id"], message=formatted, thread_ts=ctx["thread_id"]
                    )

                content = str(response.content) if response.content else ""
                send_slack_message(slack_tools, channel=ctx["channel_id"], message=content, thread_ts=ctx["thread_id"])
                upload_response_media(slack_tools, response, ctx["channel_id"], ctx["thread_id"])
        except Exception as e:
            log_error(f"Error processing slack event: {e}")
            send_slack_message(
                slack_tools,
                channel=ctx["channel_id"],
                message="Sorry, there was an error processing your message.",
                thread_ts=ctx["thread_id"],
            )

    async def _stream_slack_response(data: dict):
        from slack_sdk.web.async_client import AsyncWebClient

        event = data["event"]
        if not should_respond(event, reply_to_mentions_only):
            return

        ctx = extract_event_context(event)

        team_id = data.get("team_id") or event.get("team") or None
        # CRITICAL: recipient_user_id must be the HUMAN user, not the bot.
        # event["user"] = human who sent the message. data["authorizations"][0]["user_id"]
        # = the bot's own user ID. Using the bot ID causes Slack to stream content
        # to an invisible recipient, resulting in a blank bubble until stopStream.
        user_id = ctx.get("user") or event.get("user")

        async_client = AsyncWebClient(token=slack_tools.token, ssl=ssl)
        state = StreamState(entity_type=entity_type, entity_name=entity_name)
        stream = None

        try:
            try:
                status_kwargs: Dict[str, Any] = {
                    "channel_id": ctx["channel_id"],
                    "thread_ts": ctx["thread_id"],
                    "status": "Thinking...",
                }
                if loading_messages:
                    status_kwargs["loading_messages"] = loading_messages
                await async_client.assistant_threads_setStatus(**status_kwargs)
            except Exception:
                pass

            files, images, videos, audio = download_event_files(slack_tools, event)

            response_stream = None
            run_kwargs: Dict[str, Any] = {
                "stream": True,
                "stream_events": True,
                "user_id": ctx["user"],
                "session_id": ctx["thread_id"],
                "files": files if files else None,
                "images": images if images else None,
                "videos": videos if videos else None,
                "audio": audio if audio else None,
            }

            if agent:
                response_stream = agent.arun(ctx["message_text"], **run_kwargs)
            elif team:
                response_stream = team.arun(ctx["message_text"], **run_kwargs)  # type: ignore[assignment]
            elif workflow:
                response_stream = workflow.arun(ctx["message_text"], **run_kwargs)  # type: ignore[assignment]

            if response_stream is None:
                try:
                    await async_client.assistant_threads_setStatus(
                        channel_id=ctx["channel_id"], thread_ts=ctx["thread_id"], status=""
                    )
                except Exception:
                    pass
                return

            stream = await async_client.chat_stream(
                channel=ctx["channel_id"],
                thread_ts=ctx["thread_id"],
                recipient_team_id=team_id,
                recipient_user_id=user_id,
                task_display_mode=task_display_mode,
                buffer_size=buffer_size,
            )

            async for chunk in response_stream:
                state.collect_media(chunk)

                ev = getattr(chunk, "event", None)
                if ev:
                    if await _process_event(ev, chunk, state, stream):
                        break

                if state.text_buffer:
                    if not state.title_set:
                        state.title_set = True
                        title = ctx["message_text"][:50].strip() or "New conversation"
                        try:
                            await async_client.assistant_threads_setTitle(
                                channel_id=ctx["channel_id"], thread_ts=ctx["thread_id"], title=title
                            )
                        except Exception:
                            pass

                    await stream.append(markdown_text=state.text_buffer)
                    state.text_buffer = ""

            final_status = state.terminal_status or "complete"
            completion_chunks = state.resolve_all_pending(final_status) if state.progress_started else []
            stop_kwargs: Dict[str, Any] = {}
            if state.text_buffer:
                stop_kwargs["markdown_text"] = state.text_buffer
            if completion_chunks:
                stop_kwargs["chunks"] = completion_chunks
            await stream.stop(**stop_kwargs)

            # Upload collected media after stream ends
            upload_response_media(slack_tools, state, ctx["channel_id"], ctx["thread_id"])

        except Exception as e:
            log_error(f"Error streaming slack response: {e}")
            try:
                await async_client.assistant_threads_setStatus(
                    channel_id=ctx["channel_id"], thread_ts=ctx["thread_id"], status=""
                )
            except Exception:
                pass
            if stream is not None:
                try:
                    await stream.stop()
                except Exception:
                    pass
            send_slack_message(
                slack_tools,
                channel=ctx["channel_id"],
                message="Sorry, there was an error processing your message.",
                thread_ts=ctx["thread_id"],
            )

    async def _handle_thread_started(event: dict):
        from slack_sdk.web.async_client import AsyncWebClient

        async_client = AsyncWebClient(token=slack_tools.token, ssl=ssl)
        thread_info = event.get("assistant_thread", {})
        channel_id = thread_info.get("channel_id", "")
        thread_ts = thread_info.get("thread_ts", "")
        if not channel_id or not thread_ts:
            return

        prompts = suggested_prompts or [
            {"title": "Help", "message": "What can you help me with?"},
            {"title": "Search", "message": "Search the web for..."},
        ]
        try:
            await async_client.assistant_threads_setSuggestedPrompts(
                channel_id=channel_id, thread_ts=thread_ts, prompts=prompts
            )
        except Exception as e:
            log_error(f"Failed to set suggested prompts: {e}")

    return router
