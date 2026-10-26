import asyncio
import json
import os
import signal
from contextlib import suppress
from copy import copy
from dataclasses import field
from pathlib import Path
from typing import Any, AsyncGenerator, ClassVar, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from agno.agents._config import agent_dataclass
from agno.agents._media import (
    StagedMedia,
    accept_media,
    cleanup_run_media,
    media_prompt_block,
    remember_uploads_root,
    remove_upload_folder,
    stage_media,
    stage_prior_media,
    uploads_root,
)
from agno.agents.base import BaseExternalAgent, ExternalRunMetricsEvent, ExternalRunResult, run_coroutine_sync
from agno.metrics import ModelMetrics, RunMetrics
from agno.models.response import ToolExecution
from agno.run.agent import RunContentEvent, RunOutput, RunOutputEvent, ToolCallCompletedEvent, ToolCallStartedEvent
from agno.session.agent import AgentSession


@agent_dataclass
class PrimeAgent(BaseExternalAgent):
    """Run Prime Intellect's Prime Agent CLI through Agno and AgentOS.

    Requires an installed, authenticated ``prime-agent`` executable. Prime owns
    its model, tools, skills and native session files. Agno provides sync/async
    calls, streaming, cancellation, retries and optional database persistence.
    Prime executes code with the permissions of the server process.

    ``instructions`` supplements Prime's system prompt. ``system_prompt``
    replaces it; ``append_system_prompt`` adds further instructions. ``skills``
    contains paths passed to --skill; ``no_skills`` disables skill discovery.
    ``ephemeral`` disables native session persistence and resume. ``env`` is
    merged with the process environment. ``timeout`` bounds each CLI invocation.
    Images and files are staged for Prime's native @file input. Audio and video
    uploads and provider-enforced structured output are not supported.
    Model, provider and thinking default to Prime's configuration.
    Prime retains native JSONL session files; ``session_dir`` selects their
    directory. Agno stores runs and native session IDs, not native transcripts.

    Example:
        from agno.agents.prime import PrimeAgent

        agent = PrimeAgent(name="Prime Coder", cwd="/path/to/project")
        agent.print_response("Summarize this project", stream=True)
    """

    model: Optional[str] = None
    provider: Optional[str] = None
    thinking: Optional[str] = None
    instructions: Optional[str] = None
    system_prompt: Optional[str] = None
    append_system_prompt: Optional[str] = None
    cwd: Optional[str] = None
    keep_uploads: bool = False
    session_dir: Optional[str] = None
    ephemeral: bool = False
    skills: Optional[List[str]] = None
    no_skills: bool = False
    executable: str = "prime-agent"
    env: Dict[str, str] = field(default_factory=dict, repr=False)
    timeout: float = 600

    _sdk_name: ClassVar[str] = "prime-agent"
    _SESSION_KEY: ClassVar[str] = "prime_agent_session_id"
    _session_ids: Dict[Tuple[Optional[str], str], str] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.timeout <= 0:
            raise ValueError("PrimeAgent timeout must be positive")
        if self.thinking is not None and self.thinking not in (
            "off",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        ):
            raise ValueError("Invalid PrimeAgent thinking level")

    def _run_model(self) -> Tuple[Optional[str], Optional[str]]:
        return self.model, self.provider

    def _annotate_run_output(self, run: RunOutput, run_state: Dict[str, Any]) -> None:
        # Use the model that actually answered, including CLI defaults, per run.
        run.model = run_state.get("model", run.model)
        run.model_provider = run_state.get("provider", run.model_provider)

    def _media_kwargs(self, **media: Any) -> Dict[str, Any]:
        return accept_media(media)

    def _build_command(
        self, prompt: str, native_session_id: Optional[str], attachments: Optional[List[str]] = None
    ) -> List[str]:
        command = [self.executable, "--mode", "json"]
        appended = "\n\n".join(value for value in (self.instructions, self.append_system_prompt) if value is not None)
        for flag, value in (
            ("--provider", self.provider),
            ("--model", self.model),
            ("--thinking", self.thinking),
            ("--system-prompt", self.system_prompt),
            ("--append-system-prompt", appended or None),
            ("--cwd", str(Path(self.cwd).resolve()) if self.cwd is not None else None),
            ("--session-dir", str(Path(self.session_dir).resolve()) if self.session_dir else None),
            ("--resume", native_session_id if not self.ephemeral else None),
        ):
            if value is not None:
                command.extend([flag, value])
        if self.ephemeral:
            command.append("--no-session")
        if self.no_skills:
            command.append("--no-skills")
        for skill in self.skills or []:
            command.extend(["--skill", skill])
        command.extend("@" + path for path in attachments or [])
        # End option parsing so prompts starting with '-' or '@' stay literal.
        command.extend(["--print", "--", prompt])
        return command

    def _native_session_id(
        self, session: Optional[AgentSession], session_id: Optional[str], user_id: Optional[str]
    ) -> Optional[str]:
        if session is not None and session.user_id != user_id:
            raise ValueError("This Prime Agent session belongs to a different user")
        if self.ephemeral:
            return None
        persisted = (session.session_data or {}).get(self._SESSION_KEY) if session is not None else None
        return persisted or (self._session_ids.get((user_id, session_id)) if session_id else None)

    def _remember_session(
        self, native_id: str, session: Optional[AgentSession], session_id: Optional[str], user_id: Optional[str]
    ) -> None:
        if self.ephemeral:
            return
        if session_id:
            self._session_ids[(user_id, session_id)] = native_id
        if session is not None:
            if session.session_data is None:
                session.session_data = {}
            session.session_data[self._SESSION_KEY] = native_id

    def compact(self, session_id: str, user_id: Optional[str] = None, timeout: float = 120.0) -> bool:
        """Compact the native Prime session; return False if absent or compaction is skipped."""
        return run_coroutine_sync(self.acompact(session_id, user_id=user_id, timeout=timeout))

    async def acompact(self, session_id: str, user_id: Optional[str] = None, timeout: float = 120.0) -> bool:
        """Run Prime's /compact command while the Agno session is idle.

        Native session files must remain available on this host. CLI and
        compaction failures raise; a missing ID or a warning-level skip returns
        False. Compaction updates Prime's context, leaving Agno's history intact.
        """
        session = await self.aget_session(session_id, user_id)
        native_id = self._native_session_id(session, session_id, user_id)
        if native_id is None:
            return False
        run_id = str(uuid4())
        self._assert_session_free(session, session_id, run_id)
        self._claim_session(session, session_id, run_id)
        events = self._astream_cli("/compact", native_id, timeout=timeout)
        result: Optional[bool] = None
        try:
            async for event in events:
                if event.get("type") == "compaction_end":
                    if event.get("aborted"):
                        raise RuntimeError("Prime Agent compaction was aborted")
                    if event.get("errorMessage"):
                        if event.get("errorSeverity") != "warning":
                            raise RuntimeError(event["errorMessage"])
                        result = False
                    else:
                        result = event.get("result") is not None
            if result is None:
                raise RuntimeError("Prime Agent output ended without a compaction_end event")
            return result
        finally:
            await events.aclose()
            self._release_session(session_id, run_id)

    @staticmethod
    def _text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
            )
        return ""

    def _message_metrics(self, message: Dict[str, Any]) -> Optional[ModelMetrics]:
        usage = message.get("usage")
        if not isinstance(usage, dict) or message.get("stopReason") in ("error", "aborted"):
            return None
        cost = usage.get("cost") or {}
        counts = {
            agno_key: int(usage.get(prime_key) or 0)
            for prime_key, agno_key in (
                ("input", "input_tokens"),
                ("output", "output_tokens"),
                ("cacheRead", "cache_read_tokens"),
                ("cacheWrite", "cache_write_tokens"),
            )
        }
        return ModelMetrics(
            id=message.get("model") or self.model or "",
            provider=message.get("provider") or self.provider or "",
            total_tokens=int(usage.get("totalTokens") or sum(counts.values())),
            cost=float(cost["total"]) if isinstance(cost, dict) and cost.get("total") is not None else None,
            input_tokens=counts["input_tokens"],
            output_tokens=counts["output_tokens"],
            cache_read_tokens=counts["cache_read_tokens"],
            cache_write_tokens=counts["cache_write_tokens"],
        )

    async def _arun_adapter(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> ExternalRunResult:
        chunks: List[str] = []
        tools: Dict[str, ToolExecution] = {}
        metrics: Optional[RunMetrics] = None
        events = self._arun_adapter_stream(input, history=history, **kwargs)
        try:
            async for event in events:
                if isinstance(event, RunContentEvent) and event.content:
                    chunks.append(event.content)
                elif isinstance(event, (ToolCallStartedEvent, ToolCallCompletedEvent)) and event.tool:
                    tools[event.tool.tool_call_id or ""] = event.tool
                elif isinstance(event, ExternalRunMetricsEvent):
                    metrics = event.metrics
        finally:
            await events.aclose()
        return ExternalRunResult(content="".join(chunks), tools=list(tools.values()) or None, metrics=metrics)

    async def _arun_adapter_stream(
        self, input: Any, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> AsyncGenerator[RunOutputEvent, None]:
        if not isinstance(input, str):
            raise TypeError("PrimeAgent input must be a string")
        workspace = self.cwd
        run_id = kwargs.get("run_id") or str(uuid4())
        kwargs["run_id"] = run_id
        staged: List[StagedMedia] = []
        restaged: List[Path] = []
        created_root = False
        prepared = False
        events = None
        try:
            media = kwargs.pop("media", None)
            if media:
                created_root = not uploads_root(workspace, run_id).exists()
                staged = stage_media(workspace, run_id, media)
            if staged:
                remember_uploads_root(kwargs.get("session"), workspace)
            restaged, moved_note = stage_prior_media(workspace, kwargs.get("session"), exclude_run_id=run_id)
            prepared = True
            # Native @file arguments carry images and text files into the initial prompt.
            kwargs["attachments"] = [item.path for item in staged if item.path]
            references = media_prompt_block([item for item in staged if item.path is None])
            events = self._astream_events(input + references + moved_note, history=history, **kwargs)
            async for event in events:
                yield event
        finally:
            if events is not None:
                await events.aclose()
            if not self.keep_uploads or not prepared:
                cleanup_run_media(workspace, run_id, staged, created_root)
                for folder in restaged:
                    remove_upload_folder(folder)

    async def _astream_events(
        self, input: str, *, history: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ) -> AsyncGenerator[RunOutputEvent, None]:
        run_id = kwargs.get("run_id") or str(uuid4())
        user_id = kwargs.get("user_id")
        session: Optional[AgentSession] = kwargs.get("session")
        session_id = session.session_id if session is not None else kwargs.get("session_id")
        native_id = self._native_session_id(session, session_id, user_id)
        prompt = self._build_prompt(input, history, resumed=native_id is not None)
        run_state = kwargs.get("run_state")
        streamed_blocks: Set[int] = set()
        tools: Dict[str, ToolExecution] = {}
        models: Dict[Tuple[str, str], ModelMetrics] = {}
        totals = ModelMetrics()
        last_assistant: Dict[str, Any] = {}
        ended = False
        event_kwargs: Dict[str, Any] = {
            "run_id": run_id,
            "agent_id": self.get_id(),
            "agent_name": self.name or "",
            "session_id": session_id,
        }
        events = self._astream_cli(
            prompt, native_id, timeout=self.timeout, run_id=run_id, attachments=kwargs.get("attachments")
        )
        try:
            async for event in events:
                event_type = event.get("type")
                if event_type == "session" and event.get("id"):
                    self._remember_session(event["id"], session, session_id, user_id)
                elif event_type == "agent_start":
                    ended = False
                elif event_type == "message_start":
                    if event.get("message", {}).get("role") == "assistant":
                        streamed_blocks.clear()
                elif event_type == "message_update":
                    delta = event.get("assistantMessageEvent", {})
                    if delta.get("type") == "text_delta" and delta.get("delta"):
                        streamed_blocks.add(delta.get("contentIndex", 0))
                        yield RunContentEvent(content=delta["delta"], **event_kwargs)
                elif event_type == "message_end":
                    message = event.get("message", {})
                    if message.get("role") == "assistant":
                        last_assistant = message
                        if run_state is not None:
                            for key in ("model", "provider"):
                                if message.get(key):
                                    run_state[key] = message[key]
                        usage = self._message_metrics(message)
                        if usage is not None:
                            totals.accumulate(usage)
                            model_key = (usage.provider, usage.id)
                            models.setdefault(model_key, ModelMetrics(id=usage.id, provider=usage.provider)).accumulate(
                                usage
                            )
                        content = message.get("content", [])
                        if isinstance(content, str):
                            if not streamed_blocks and content:
                                yield RunContentEvent(content=content, **event_kwargs)
                        elif isinstance(content, list):
                            for index, block in enumerate(content):
                                if (
                                    isinstance(block, dict)
                                    and block.get("type") == "text"
                                    and index not in streamed_blocks
                                ):
                                    if block.get("text"):
                                        yield RunContentEvent(content=block["text"], **event_kwargs)
                    elif message.get("role") == "toolResult" and message.get("toolCallId") in tools:
                        # Some CLI versions expose isError only on the completed tool message.
                        tool = tools[message["toolCallId"]]
                        is_error = bool(message.get("isError"))
                        if tool.tool_call_error != is_error:
                            tool.tool_call_error = is_error
                            yield ToolCallCompletedEvent(tool=copy(tool), **event_kwargs)
                elif event_type == "tool_execution_start":
                    tool_id = event["toolCallId"]
                    args = event.get("args", {})
                    tool = ToolExecution(
                        tool_call_id=tool_id,
                        tool_name=event.get("toolName"),
                        tool_args=args if isinstance(args, dict) else {"input": args},
                    )
                    tools[tool_id] = tool
                    yield ToolCallStartedEvent(tool=copy(tool), **event_kwargs)
                elif event_type == "tool_execution_end":
                    tool_id = event["toolCallId"]
                    tool = tools.setdefault(
                        tool_id, ToolExecution(tool_call_id=tool_id, tool_name=event.get("toolName"))
                    )
                    result = event.get("result", {})
                    result_text = self._text(result.get("content")) if isinstance(result, dict) else str(result)
                    tool.result = result_text or json.dumps(result, ensure_ascii=False)
                    tool.tool_call_error = bool(
                        event.get("isError") or (isinstance(result, dict) and result.get("isError"))
                    )
                    if run_state is not None:
                        run_state.setdefault("tools", {})[tool_id] = tool
                    yield ToolCallCompletedEvent(tool=copy(tool), **event_kwargs)
                elif event_type == "agent_end":
                    ended = True
            if last_assistant.get("stopReason") in ("error", "aborted"):
                raise RuntimeError(last_assistant.get("errorMessage") or "Prime Agent run failed or was aborted")
            if not ended:
                raise RuntimeError("Prime Agent output ended without an agent_end event")
            if models:
                yield ExternalRunMetricsEvent(
                    metrics=self._build_metrics(totals, list(models.values())), **event_kwargs
                )
        finally:
            await events.aclose()

    @staticmethod
    def _signal_process(process: Any, *, kill: bool = False) -> None:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL if kill else signal.SIGTERM)
                elif kill:
                    process.kill()
                else:
                    process.terminate()

    async def _ainterrupt_run(self, handle: Any) -> None:
        self._signal_process(handle)
        try:
            await asyncio.wait_for(handle.wait(), timeout=5)
        except asyncio.TimeoutError:
            self._signal_process(handle, kill=True)

    async def _astream_cli(
        self,
        prompt: str,
        native_id: Optional[str],
        *,
        timeout: float,
        run_id: Optional[str] = None,
        attachments: Optional[List[str]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if timeout <= 0:
            raise ValueError("PrimeAgent timeout must be positive")
        try:
            process = await asyncio.create_subprocess_exec(
                *self._build_command(prompt, native_id, attachments),
                cwd=self.cwd,
                env={**os.environ, **self.env},
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=os.name == "posix",
                limit=16 * 1024 * 1024,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "Prime Agent executable or working directory not found. Install prime-agent, "
                "authenticate with /login, and check executable= and cwd=."
            ) from exc
        if run_id is not None:
            self._set_run_handle(run_id, process)
        stderr_tail = bytearray()

        async def drain_stderr() -> None:
            if process.stderr is not None:
                while True:
                    chunk = await process.stderr.read(4096)
                    if not chunk:
                        break
                    stderr_tail.extend(chunk)
                    del stderr_tail[:-8192]

        stderr_task = asyncio.create_task(drain_stderr())
        deadline = asyncio.get_running_loop().time() + timeout
        try:
            assert process.stdout is not None
            while True:
                line = await asyncio.wait_for(
                    process.stdout.readline(), timeout=max(0, deadline - asyncio.get_running_loop().time())
                )
                if not line:
                    break
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise RuntimeError("Prime Agent emitted invalid JSON in --mode json") from exc
                if not isinstance(event, dict):
                    raise RuntimeError("Prime Agent emitted a non-object JSON event")
                if event.get("type") == "error":
                    raise RuntimeError(event.get("message") or "Prime Agent run failed")
                yield event
            await asyncio.wait_for(process.wait(), timeout=max(0, deadline - asyncio.get_running_loop().time()))
            await asyncio.wait_for(stderr_task, timeout=max(0, deadline - asyncio.get_running_loop().time()))
            if process.returncode != 0:
                detail = stderr_tail.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Prime Agent exited with code {process.returncode}: {detail}")
        except asyncio.TimeoutError as exc:
            raise TimeoutError(f"Prime Agent run exceeded {timeout} seconds") from exc
        finally:
            if run_id is not None:
                self._clear_run_handle(run_id)
            stderr_task.cancel()
            with suppress(asyncio.CancelledError):
                await stderr_task
            if process.returncode is None:
                self._signal_process(process)
                try:
                    await asyncio.wait_for(process.communicate(), timeout=5)
                except asyncio.TimeoutError:
                    self._signal_process(process, kill=True)
                    await process.communicate()
