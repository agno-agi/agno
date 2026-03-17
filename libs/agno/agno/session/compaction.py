from dataclasses import dataclass
from datetime import datetime
from textwrap import dedent
from typing import TYPE_CHECKING, Any, List, Optional, Union

from agno.models.base import Model
from agno.models.message import Message
from agno.models.utils import get_model
from agno.session.summary import SessionSummary
from agno.utils.log import log_debug, log_warning

if TYPE_CHECKING:
    from agno.metrics import RunMetrics
    from agno.run.team import TeamRunOutput
    from agno.run.agent import RunOutput
    from agno.session import Session


DEFAULT_CONTEXT_COMPACTION_PROMPT = dedent("""\
    You are compacting a long-running conversation into a concise working summary.

    Your goal is to preserve the information that matters for future turns while removing repetition.

    Preserve:
    - User goals, requirements, preferences, and constraints
    - Decisions that were made
    - Facts, values, IDs, URLs, dates, and technical details that may matter later
    - Open questions, unresolved issues, and pending follow-ups

    Remove:
    - Repetition
    - Small talk and filler
    - Long intermediate reasoning that does not affect future turns

    Write a compact summary that can be used as context for future replies.
    Do not invent information.
    Return only the updated summary text.\
""")


@dataclass
class ContextCompactionManager:
    model: Optional[Union[Model, str]] = None
    enabled: bool = True
    compact_token_limit: Optional[int] = None
    compact_message_limit: Optional[int] = None
    keep_last_n_runs: int = 3
    compaction_prompt: Optional[str] = None
    compact_request_message: str = "Update the running conversation summary."

    def __post_init__(self) -> None:
        if self.compact_token_limit is None and self.compact_message_limit is None:
            self.compact_message_limit = 40

    def should_compact(
        self,
        messages: List[Message],
        model: Optional[Model] = None,
        tools: Optional[List[Any]] = None,
        response_format: Optional[Any] = None,
    ) -> bool:
        if not self.enabled:
            return False

        if self.compact_message_limit is not None and len(messages) >= self.compact_message_limit:
            return True

        if self.compact_token_limit is not None and model is not None:
            tokens = model.count_tokens(messages, tools, output_schema=response_format)
            if tokens >= self.compact_token_limit:
                return True

        return False

    async def ashould_compact(
        self,
        messages: List[Message],
        model: Optional[Model] = None,
        tools: Optional[List[Any]] = None,
        response_format: Optional[Any] = None,
    ) -> bool:
        if not self.enabled:
            return False

        if self.compact_message_limit is not None and len(messages) >= self.compact_message_limit:
            return True

        if self.compact_token_limit is not None and model is not None:
            tokens = await model.acount_tokens(messages, tools, output_schema=response_format)
            if tokens >= self.compact_token_limit:
                return True

        return False

    def _get_top_level_completed_runs(self, session: "Session") -> List[Union["RunOutput", "TeamRunOutput"]]:
        from agno.run.base import RunStatus

        filtered_runs: List[Union["RunOutput", "TeamRunOutput"]] = []
        last_compacted_run_id = session.get_last_compacted_run_id()
        start_collecting = last_compacted_run_id is None or not any(
            run.run_id == last_compacted_run_id for run in session.runs or []
        )

        for run in session.runs or []:
            if not start_collecting:
                if run.run_id == last_compacted_run_id:
                    start_collecting = True
                continue

            if getattr(run, "parent_run_id", None) is not None:
                continue

            status = getattr(run, "status", None)
            if status in {RunStatus.paused, RunStatus.cancelled, RunStatus.error}:
                continue

            filtered_runs.append(run)

        return filtered_runs

    def _get_runs_to_compact(self, session: "Session") -> List[Union["RunOutput", "TeamRunOutput"]]:
        runs = self._get_top_level_completed_runs(session)
        if len(runs) <= self.keep_last_n_runs:
            return []
        return runs[: -self.keep_last_n_runs]

    def _build_conversation_transcript(self, runs: List[Union["RunOutput", "TeamRunOutput"]]) -> str:
        transcript_parts: List[str] = []

        for run in runs:
            for message in run.messages or []:
                if message.role == "user":
                    transcript_parts.append(f"User: {message.content}")
                elif message.role in {"assistant", "model"}:
                    transcript_parts.append(f"Assistant: {message.content}")
                elif message.role == "tool":
                    tool_name = message.tool_name or "unknown"
                    tool_content = message.compressed_content or message.content
                    if tool_content:
                        transcript_parts.append(f"Tool[{tool_name}]: {tool_content}")

        return "\n".join(part for part in transcript_parts if part)

    def _get_compaction_messages(self, session: "Session") -> Optional[List[Message]]:
        runs_to_compact = self._get_runs_to_compact(session)
        if not runs_to_compact:
            return None

        self.model = get_model(self.model)
        if self.model is None:
            log_warning("No context compaction model available")
            return None

        transcript = self._build_conversation_transcript(runs_to_compact)
        if transcript == "":
            return None

        system_prompt = self.compaction_prompt or DEFAULT_CONTEXT_COMPACTION_PROMPT
        if session.summary is not None and session.summary.summary:
            system_prompt += f"\n\nExisting summary:\n{session.summary.summary}\n"

        system_prompt += f"\n\n<conversation_to_compact>\n{transcript}\n</conversation_to_compact>"

        return [
            Message(role="system", content=system_prompt),
            Message(role="user", content=self.compact_request_message),
        ]

    def compact_session(
        self,
        session: "Session",
        run_metrics: Optional["RunMetrics"] = None,
    ) -> bool:
        log_debug("Compacting session context", center=True)
        messages = self._get_compaction_messages(session)
        runs_to_compact = self._get_runs_to_compact(session)
        if not messages or not runs_to_compact:
            return False

        response = self.model.response(messages=messages)  # type: ignore[union-attr]
        compacted_summary = response.content.strip() if isinstance(response.content, str) else None
        if not compacted_summary:
            return False

        if run_metrics is not None:
            from agno.metrics import ModelType, accumulate_model_metrics

            accumulate_model_metrics(response, self.model, ModelType.SESSION_SUMMARY_MODEL, run_metrics)

        session.summary = SessionSummary(summary=compacted_summary, updated_at=datetime.now())
        session.set_last_compacted_run_id(runs_to_compact[-1].run_id)
        log_debug(f"Compacted {len(runs_to_compact)} runs into session summary")
        return True

    async def acompact_session(
        self,
        session: "Session",
        run_metrics: Optional["RunMetrics"] = None,
    ) -> bool:
        log_debug("Compacting session context (async)", center=True)
        messages = self._get_compaction_messages(session)
        runs_to_compact = self._get_runs_to_compact(session)
        if not messages or not runs_to_compact:
            return False

        response = await self.model.aresponse(messages=messages)  # type: ignore[union-attr]
        compacted_summary = response.content.strip() if isinstance(response.content, str) else None
        if not compacted_summary:
            return False

        if run_metrics is not None:
            from agno.metrics import ModelType, accumulate_model_metrics

            accumulate_model_metrics(response, self.model, ModelType.SESSION_SUMMARY_MODEL, run_metrics)

        session.summary = SessionSummary(summary=compacted_summary, updated_at=datetime.now())
        session.set_last_compacted_run_id(runs_to_compact[-1].run_id)
        log_debug(f"Compacted {len(runs_to_compact)} runs into session summary")
        return True
