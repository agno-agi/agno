"""Conversation history compaction manager.

Inspired by OpenCode's auto-compaction mechanism. When the conversation history
approaches the model's context window limit, this manager summarises the entire
history into a compact message, drastically reducing token usage while preserving
essential context.

This is different from tool-result *compression* (which only shortens individual
tool outputs).  Compaction replaces the *whole* conversation with a summary.

When ``enable_compaction=True`` the compaction manager takes full ownership of
history loading — ``add_history_to_context`` is silently ignored so the two
mechanisms never overlap.

Typical usage::

    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        enable_compaction=True,
        compaction_manager=CompactionManager(
            context_usage_threshold=0.75,
            preserve_last_n_messages=2,
        ),
    )
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from textwrap import dedent
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Set, Tuple, Type, Union

from agno.utils.log import log_debug, log_info, log_warning

if TYPE_CHECKING:
    from agno.metrics import RunMetrics
    from agno.models.base import Model
    from agno.models.message import Message
    from agno.session.agent import AgentSession
    from agno.tools.function import Function

# ---------------------------------------------------------------------------
# Default compaction prompt
# ---------------------------------------------------------------------------

DEFAULT_COMPACTION_PROMPT = dedent("""\
    You are summarizing a conversation between a user and an AI assistant to preserve essential context.

    Your goal: Create a concise but comprehensive summary that allows the conversation to continue seamlessly.

    ALWAYS PRESERVE:
    - User's original goal/request (as close to verbatim as possible)
    - Key decisions made and their rationale
    - Work that has been completed (with file paths if relevant)
    - Pending tasks and next steps
    - Important technical details discovered (APIs, patterns, constraints)
    - User preferences and constraints established
    - Current state of the codebase or task

    BE CONCISE:
    - Focus on what matters for continuing the work
    - Avoid implementation details unless critical
    - Use bullet points for clarity

    FORMAT:
    [COMPACTION SUMMARY]
    ==================
    USER REQUEST: <original request>
    GOAL: <one sentence describing the goal>
    COMPLETED: <what was done>
    PENDING: <what remains>
    KEY DECISIONS: <important decisions made>
    IMPORTANT FILES: <relevant file paths>
    CONSTRAINTS: <established constraints>
    CONTEXT FOR CONTINUATION: <what the assistant needs to know>
    ==================
    """)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_compacted_run_ids(session: "AgentSession") -> Set[str]:
    """Scan session runs (newest first) to find the latest compaction boundary.

    Returns the set of run IDs that were compacted by the most recent
    compaction operation.  Empty set if no compaction has occurred.
    """
    for run in reversed(session.runs or []):
        if hasattr(run, "compacted_run_ids") and run.compacted_run_ids:
            return set(run.compacted_run_ids)
    return set()


# ---------------------------------------------------------------------------
# Compaction Manager
# ---------------------------------------------------------------------------


@dataclass
class CompactionManager:
    """Manages conversation history compaction.

    Compaction is triggered when the token count approaches the model's context
    window limit. The entire conversation history is replaced with a summary
    message, preserving essential context while drastically reducing token usage.

    Attributes:
        model: Model used for generating the summary (defaults to agent's model).
        context_usage_threshold: Fraction of context window at which compaction triggers.
        context_reserve_tokens: Tokens reserved for model output (not included in threshold).
        preserve_last_n_messages: Number of recent messages to preserve after compaction.
        compaction_prompt: Custom prompt for summary generation.
        auto_compact: Whether to automatically trigger compaction.
    """

    # Model used for generating the summary (defaults to agent's model if None)
    model: Optional["Model"] = None

    # Trigger threshold: compaction activates when tokens >= context_window * threshold
    context_usage_threshold: float = 0.75

    # Tokens reserved for model output (subtracted from threshold calculation)
    context_reserve_tokens: int = 4000

    # Number of recent messages to preserve after compaction
    preserve_last_n_messages: int = 2

    # Custom prompt for summary generation
    compaction_prompt: Optional[str] = None

    # Whether to automatically trigger compaction
    auto_compact: bool = True

    # Statistics tracking
    stats: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # History loading (compaction-owned, replaces add_history_to_context)
    # ------------------------------------------------------------------

    def load_history(self, session: "AgentSession") -> Tuple[List["Message"], List[str]]:
        """Load conversation history from the session, respecting compaction boundaries.

        This is the sole entry point for history loading when compaction is enabled.
        It skips runs that have already been compacted (their content lives in a
        summary message stored in a later run).

        Args:
            session: The current agent session.

        Returns:
            A tuple of (history_messages, loaded_run_ids).
            *history_messages* are deep-copied and tagged with ``from_history=True``.
            *loaded_run_ids* is the list of run IDs whose messages were included,
            needed by :meth:`compact` to populate ``compacted_run_ids``.
        """
        compacted_ids = _find_compacted_run_ids(session)

        # Collect runs whose messages should be loaded, skipping compacted ones
        loaded_run_ids: List[str] = []
        all_messages: List["Message"] = []

        for run in session.runs or []:
            # Skip runs whose content was already compacted
            if hasattr(run, "run_id") and run.run_id in compacted_ids:
                continue
            # Skip empty runs
            if not run or not run.messages:
                continue
            # Skip paused/cancelled/error runs
            from agno.run.agent import RunStatus

            if hasattr(run, "status") and run.status in (RunStatus.paused, RunStatus.cancelled, RunStatus.error):
                continue

            loaded_run_ids.append(run.run_id)

            for msg in run.messages:
                if not msg.add_to_agent_memory:
                    continue
                msg_copy = deepcopy(msg)
                msg_copy.from_history = True
                all_messages.append(msg_copy)

        log_debug(
            f"Compaction loaded {len(all_messages)} messages from {len(loaded_run_ids)} runs "
            f"(skipped {len(compacted_ids)} compacted runs)"
        )
        return all_messages, loaded_run_ids

    # ------------------------------------------------------------------
    # Threshold & trigger
    # ------------------------------------------------------------------

    def get_effective_token_threshold(self, model: Optional["Model"]) -> Optional[int]:
        """Calculate the token threshold for triggering compaction.

        Args:
            model: The model being used (provides context_window).

        Returns:
            Token threshold, or None if context_window unavailable.
        """
        if model is None:
            return None

        context_window = getattr(model, "context_window", None)
        if context_window is None:
            log_warning(f"Model {model.id} does not have context_window defined")
            return None

        threshold = int(context_window * self.context_usage_threshold - self.context_reserve_tokens)
        return max(threshold, 1000)  # Minimum 1000 tokens

    def should_compact(
        self,
        messages: List["Message"],
        tools: Optional[Sequence[Union["Function", Dict[str, Any]]]] = None,
        model: Optional["Model"] = None,
        response_format: Optional[Union[Dict, Type]] = None,
    ) -> bool:
        """Check if compaction should be triggered.

        Args:
            messages: Current conversation messages.
            tools: Tools available (for token counting).
            model: The model being used.
            response_format: Output schema (for token counting).

        Returns:
            True if compaction should be triggered.
        """
        if not self.auto_compact:
            return False

        if model is None:
            return False

        threshold = self.get_effective_token_threshold(model)
        if threshold is None:
            return False

        current_tokens = model.count_tokens(messages, tools, response_format)

        if current_tokens >= threshold:
            log_info(
                f"Compaction triggered: {current_tokens} tokens >= {threshold} threshold "
                f"(context_window={getattr(model, 'context_window', 'unknown')})"
            )
            return True

        return False

    async def ashould_compact(
        self,
        messages: List["Message"],
        tools: Optional[Sequence[Union["Function", Dict[str, Any]]]] = None,
        model: Optional["Model"] = None,
        response_format: Optional[Union[Dict, Type]] = None,
    ) -> bool:
        """Async version of should_compact. Token counting is CPU-bound, so this just calls the sync version."""
        return self.should_compact(messages, tools, model, response_format)

    # ------------------------------------------------------------------
    # Compaction (sync)
    # ------------------------------------------------------------------

    def compact(
        self,
        messages: List["Message"],
        loaded_run_ids: List[str],
        model: Optional["Model"] = None,
        run_metrics: Optional["RunMetrics"] = None,
    ) -> Tuple[List["Message"], List[str]]:
        """Compact the conversation history into a summary message.

        Args:
            messages: Current conversation messages.
            loaded_run_ids: Run IDs whose messages are included (from :meth:`load_history`).
            model: Model to use for summary generation.
            run_metrics: Optional metrics tracker.

        Returns:
            A tuple of (new_messages, compacted_run_ids).
            *new_messages* is ``[summary] + preserved_recent_messages``.
            *compacted_run_ids* should be written to ``run_response.compacted_run_ids``.
        """
        if not messages:
            return messages, []

        summary_model = model or self.model
        if summary_model is None:
            log_warning("No model available for compaction summary generation")
            return messages, []

        # Generate summary of conversation history
        summary_content = self._generate_summary(messages, summary_model, run_metrics)

        # Create the compaction summary message
        summary_message = self._create_summary_message(summary_content)

        # Preserve the last N messages
        preserved_messages = (
            messages[-self.preserve_last_n_messages :] if len(messages) > self.preserve_last_n_messages else []
        )

        new_messages = [summary_message] + preserved_messages

        # Update stats
        self._update_stats(messages, new_messages, summary_model)

        return new_messages, loaded_run_ids

    # ------------------------------------------------------------------
    # Compaction (async)
    # ------------------------------------------------------------------

    async def acompact(
        self,
        messages: List["Message"],
        loaded_run_ids: List[str],
        model: Optional["Model"] = None,
        run_metrics: Optional["RunMetrics"] = None,
    ) -> Tuple[List["Message"], List[str]]:
        """Async compact the conversation history.

        Identical to :meth:`compact` but uses the async model API.
        """
        if not messages:
            return messages, []

        summary_model = model or self.model
        if summary_model is None:
            log_warning("No model available for compaction summary generation")
            return messages, []

        summary_content = await self._agenerate_summary(messages, summary_model, run_metrics)

        summary_message = self._create_summary_message(summary_content)

        preserved_messages = (
            messages[-self.preserve_last_n_messages :] if len(messages) > self.preserve_last_n_messages else []
        )

        new_messages = [summary_message] + preserved_messages

        self._update_stats(messages, new_messages, summary_model)

        return new_messages, loaded_run_ids

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_stats(self, old_messages: List["Message"], new_messages: List["Message"], model: "Model") -> None:
        original_count = len(old_messages)
        original_tokens = model.count_tokens(old_messages) if model else 0
        new_tokens = model.count_tokens(new_messages) if model else 0

        self.stats["compactions_performed"] = self.stats.get("compactions_performed", 0) + 1
        self.stats["messages_before"] = original_count
        self.stats["messages_after"] = len(new_messages)
        self.stats["tokens_before"] = original_tokens
        self.stats["tokens_after"] = new_tokens
        self.stats["tokens_saved"] = original_tokens - new_tokens

        log_debug(
            f"Compaction completed: {original_count} messages -> {len(new_messages)} messages, "
            f"{original_tokens} tokens -> {new_tokens} tokens (saved {original_tokens - new_tokens})"
        )

    def _generate_summary(
        self,
        messages: List["Message"],
        model: "Model",
        run_metrics: Optional["RunMetrics"] = None,
    ) -> str:
        """Generate a summary of the conversation history using the model."""
        from agno.models.message import Message

        history_text = self._format_history_for_summary(messages)

        prompt = self.compaction_prompt or DEFAULT_COMPACTION_PROMPT
        summary_messages = [
            Message(role="system", content=prompt),
            Message(role="user", content=f"Conversation history to summarize:\n\n{history_text}"),
        ]

        try:
            response = model.response(messages=summary_messages)

            if run_metrics is not None and response.response_usage is not None:
                from agno.metrics import ModelType, accumulate_model_metrics

                accumulate_model_metrics(response, model, ModelType.COMPRESSION_MODEL, run_metrics)

            return response.content or "Summary generation failed."

        except Exception as e:
            log_warning(f"Failed to generate compaction summary: {e}")
            return self._create_fallback_summary(messages)

    async def _agenerate_summary(
        self,
        messages: List["Message"],
        model: "Model",
        run_metrics: Optional["RunMetrics"] = None,
    ) -> str:
        """Async generate a summary of the conversation history."""
        from agno.models.message import Message

        history_text = self._format_history_for_summary(messages)

        prompt = self.compaction_prompt or DEFAULT_COMPACTION_PROMPT
        summary_messages = [
            Message(role="system", content=prompt),
            Message(role="user", content=f"Conversation history to summarize:\n\n{history_text}"),
        ]

        try:
            response = await model.aresponse(messages=summary_messages)

            if run_metrics is not None and response.response_usage is not None:
                from agno.metrics import ModelType, accumulate_model_metrics

                accumulate_model_metrics(response, model, ModelType.COMPRESSION_MODEL, run_metrics)

            return response.content or "Summary generation failed."

        except Exception as e:
            log_warning(f"Failed to generate compaction summary: {e}")
            return self._create_fallback_summary(messages)

    def _format_history_for_summary(self, messages: List["Message"]) -> str:
        """Format conversation messages into a text representation for summarization."""
        lines = []
        for i, msg in enumerate(messages):
            role = msg.role or "unknown"
            content = msg.content

            if isinstance(content, str):
                content_preview = content[:500] if len(content) > 500 else content
            elif isinstance(content, list):
                text_parts = [
                    item.get("text", "") if isinstance(item, dict) and item.get("type") == "text" else ""
                    for item in content
                ]
                content_preview = " ".join(text_parts)[:500]
            else:
                content_preview = str(content)[:500]

            tool_info = ""
            if msg.tool_calls:
                tool_names = [tc.get("function", {}).get("name", "unknown") for tc in msg.tool_calls]
                tool_info = f" [tools: {', '.join(tool_names)}]"
            if msg.role == "tool" and msg.tool_name:
                tool_info = f" [tool: {msg.tool_name}]"

            lines.append(f"[{i}] {role}{tool_info}: {content_preview}")

        return "\n".join(lines)

    def _create_summary_message(self, summary_content: str) -> "Message":
        """Create a Message object containing the compaction summary."""
        from agno.models.message import Message

        return Message(
            role="user",
            content=f"[Previous conversation compacted]\n\n{summary_content}",
        )

    def _create_fallback_summary(self, messages: List["Message"]) -> str:
        """Create a simple fallback summary when model summarization fails."""
        if not messages:
            return "No conversation history."

        first_user_msg = None
        for msg in messages:
            if msg.role == "user":
                first_user_msg = msg
                break

        last_assistant_msg = None
        for msg in reversed(messages):
            if msg.role == "assistant":
                last_assistant_msg = msg
                break

        summary_parts = ["[COMPACTION SUMMARY - FALLBACK]"]

        if first_user_msg:
            content = first_user_msg.content
            if isinstance(content, str):
                summary_parts.append(f"ORIGINAL REQUEST: {content[:200]}")

        if last_assistant_msg:
            content = last_assistant_msg.content
            if isinstance(content, str):
                summary_parts.append(f"RECENT WORK: {content[:200]}")

        summary_parts.append(f"TOTAL MESSAGES: {len(messages)}")
        summary_parts.append("Please review the preserved recent messages for current context.")

        return "\n".join(summary_parts)
