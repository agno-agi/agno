"""
Conversation Compaction Demo
============================

Demonstrates automatic conversation compaction: when the conversation history
approaches the model's context window limit, the entire history is summarised
into a compact message, drastically reducing token usage while preserving
essential context.

Output files (in tmp/):
  compaction_messages.json  - Messages sent to the LLM before/after compaction
  compaction_demo.db        - SQLite session storage

Setup (bash):
    export AGNO_MODEL_BASE_URL="http://your-server/v1"
    export AGNO_MODEL_API_KEY="sk-xxx"
    export AGNO_MODEL_ID="model_id"

Run:
    .venvs/demo/bin/python cookbook/02_agents/03_context_management/conversation_compaction.py

Debug in VS Code:
    Use the "Compaction Demo" launch configuration in .vscode/launch.json
"""

import json
import os
import random
import string
import time
from typing import Any, Dict, List, Optional, Type, Union

from agno.agent import Agent
from agno.compaction import CompactionManager
from agno.db.sqlite import SqliteDb
from agno.metrics import RunMetrics
from agno.models.base import Model
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.models.response import ModelResponse
from agno.tools.function import Function


# ---------------------------------------------------------------------------
# Custom tools that generate very long output to fill the context window
# ---------------------------------------------------------------------------

def generate_report(topic: str, pages: int = 5) -> str:
    """Generate a very long report on the given topic.

    Args:
        topic: The topic to generate a report about.
        pages: Number of pages (each ~800 words).
    """
    paragraphs = []
    for page in range(pages):
        for para in range(8):
            words = ["".join(random.choices(string.ascii_lowercase, k=random.randint(3, 10))) for _ in range(20)]
            paragraphs.append(" ".join(words).capitalize() + ".")
    return (
        f"===== REPORT: {topic.upper()} =====\n\n"
        + "\n\n".join(paragraphs)
        + f"\n\n===== END OF REPORT ({pages} pages, ~{pages * 800} words) ====="
    )


def lookup_data(query: str, records: int = 300) -> str:
    """Look up data records matching the query.

    Args:
        query: The search query.
        records: Number of records to return.
    """
    rows = []
    for i in range(records):
        row = {
            "id": i,
            "query": query,
            "name": "".join(random.choices(string.ascii_letters, k=12)),
            "value": random.randint(1000, 99999),
            "category": random.choice(["A", "B", "C", "D"]),
            "status": random.choice(["active", "pending", "archived"]),
            "description": " ".join(
                "".join(random.choices(string.ascii_lowercase, k=random.randint(4, 8)))
                for _ in range(10)
            ),
        }
        rows.append(json.dumps(row))
    return f"Data lookup results for '{query}':\nFound {records} records.\n\n" + "\n".join(rows)


# ---------------------------------------------------------------------------
# Model from env vars (no hardcoded secrets)
# ---------------------------------------------------------------------------

def get_model() -> OpenAILike:
    base_url = os.environ.get("AGNO_MODEL_BASE_URL")
    api_key = os.environ.get("AGNO_MODEL_API_KEY")
    model_id = os.environ.get("AGNO_MODEL_ID", "model_id")
    if not base_url or not api_key:
        raise ValueError(
            "Set env vars:\n"
            "  AGNO_MODEL_BASE_URL='http://your-server/v1'\n"
            "  AGNO_MODEL_API_KEY='sk-xxx'\n"
            "  AGNO_MODEL_ID='model_id'"
        )
    return OpenAILike(
        id=model_id,
        base_url=base_url,
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# Message logger — intercepts model calls to dump actual messages sent to LLM
# ---------------------------------------------------------------------------

class MessageLogger:
    """Captures every call to model.response() and dumps the messages.

    We monkey-patch the model instance so every LLM call (normal + compaction
    summary generation) is logged without touching framework code.
    """

    def __init__(self, path: str):
        self.path = path
        self.entries: list = []

    def _serialise_messages(self, messages: List[Message]) -> list:
        """Convert Message list to JSON-safe dicts with truncated content."""
        result = []
        for m in messages:
            d: Dict[str, Any] = {"role": m.role}
            content = m.content
            if isinstance(content, str):
                d["content_length"] = len(content)
                d["content_preview"] = content[:300] + "..." if len(content) > 300 else content
            elif isinstance(content, list):
                d["content_type"] = "list"
                d["content_length"] = len(str(content))
            else:
                d["content"] = content
            d["from_history"] = getattr(m, "from_history", False)
            if m.tool_calls:
                d["tool_calls"] = [
                    tc.get("function", {}).get("name", "unknown") if isinstance(tc, dict) else str(tc)
                    for tc in m.tool_calls
                ]
            if m.tool_name:
                d["tool_name"] = m.tool_name
            result.append(d)
        return result

    def log_model_call(self, label: str, messages: List[Message], extra: dict | None = None) -> None:
        entry: Dict[str, Any] = {
            "label": label,
            "message_count": len(messages),
            "roles_summary": {},
            "messages": self._serialise_messages(messages),
        }
        # Count by role
        for m in messages:
            r = m.role or "unknown"
            entry["roles_summary"][r] = entry["roles_summary"].get(r, 0) + 1
        if extra:
            entry.update(extra)
        self.entries.append(entry)
        self._flush()

    def _flush(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.entries, f, indent=2, ensure_ascii=False)


def patch_model_for_logging(model: Model, logger: MessageLogger) -> None:
    """Monkey-patch model.response / model.aresponse to log messages before each call."""

    _original_response = model.response
    _call_counter = [0]

    def _logged_response(
        messages: List[Message],
        response_format: Optional[Union[Dict, Type]] = None,
        tools: Optional[List[Union[Function, dict]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        tool_call_limit: Optional[int] = None,
        run_response=None,
        send_media_to_model: bool = True,
        compression_manager=None,
    ) -> ModelResponse:
        _call_counter[0] += 1
        call_index = len(logger.entries)
        logger.log_model_call(
            label=f"LLM call #{_call_counter[0]}",
            messages=messages,
            extra={
                "tools_count": len(tools) if tools else 0,
            },
        )
        result = _original_response(
            messages=messages,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            tool_call_limit=tool_call_limit,
            run_response=run_response,
            send_media_to_model=send_media_to_model,
            compression_manager=compression_manager,
        )
        # Patch the entry with actual token counts from the response
        if result is not None:
            usage = result.response_usage
            logger.entries[call_index].update({
                "input_tokens": getattr(usage, "input_tokens", None) if usage else result.input_tokens,
                "output_tokens": getattr(usage, "output_tokens", None) if usage else result.output_tokens,
                "total_tokens": getattr(usage, "total_tokens", None) if usage else result.total_tokens,
                "reasoning_tokens": getattr(usage, "reasoning_tokens", None) if usage else result.reasoning_tokens,
            })
            logger._flush()
        return result

    model.response = _logged_response

    # Also patch async variant
    _original_aresponse = model.aresponse

    async def _logged_aresponse(
        messages: List[Message],
        response_format: Optional[Union[Dict, Type]] = None,
        tools: Optional[List[Union[Function, dict]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        tool_call_limit: Optional[int] = None,
        run_response=None,
        send_media_to_model: bool = True,
        compression_manager=None,
    ) -> ModelResponse:
        _call_counter[0] += 1
        call_index = len(logger.entries)
        logger.log_model_call(
            label=f"LLM call #{_call_counter[0]} (async)",
            messages=messages,
            extra={
                "tools_count": len(tools) if tools else 0,
            },
        )
        result = await _original_aresponse(
            messages=messages,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            tool_call_limit=tool_call_limit,
            run_response=run_response,
            send_media_to_model=send_media_to_model,
            compression_manager=compression_manager,
        )
        if result is not None:
            usage = result.response_usage
            logger.entries[call_index].update({
                "input_tokens": getattr(usage, "input_tokens", None) if usage else result.input_tokens,
                "output_tokens": getattr(usage, "output_tokens", None) if usage else result.output_tokens,
                "total_tokens": getattr(usage, "total_tokens", None) if usage else result.total_tokens,
                "reasoning_tokens": getattr(usage, "reasoning_tokens", None) if usage else result.reasoning_tokens,
            })
            logger._flush()
        return result

    model.aresponse = _logged_aresponse


# ---------------------------------------------------------------------------
# Token counting speed test
# ---------------------------------------------------------------------------

def benchmark_token_counting(model: Model) -> None:
    from agno.utils.tokens import _select_tokenizer

    sizes = [10, 100, 1000, 5000, 10000]
    print("\n  Token counting speed benchmark:")
    print(f"  {'Messages':>10} | {'Chars':>12} | {'Tokens':>10} | {'Time (ms)':>10}")
    print(f"  {'-' * 10}-+-{'-' * 12}-+-{'-' * 10}-+-{'-' * 10}")

    for n in sizes:
        msgs = [Message(role="user", content="word " * 200) for _ in range(n)]
        total_chars = sum(len(m.content or "") for m in msgs)
        t0 = time.perf_counter()
        tokens = model.count_tokens(msgs)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(f"  {n:>10} | {total_chars:>12,} | {tokens:>10,} | {elapsed_ms:>10.1f}")

    tokenizer_type, _ = _select_tokenizer(model.id)
    print(f"\n  Tokenizer: {tokenizer_type} ({model.id})")
    if tokenizer_type == "tiktoken":
        print("  tiktoken is Rust-based, very fast (~1M tokens/sec)")
    elif tokenizer_type == "huggingface":
        print("  HuggingFace tokenizers are Rust-based, very fast")
    else:
        print("  No tokenizer installed, using fallback: chars/4 (fast but inaccurate)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Clean up previous demo data (commented out to preserve output for inspection)
    # for f in ["tmp/compaction_demo.db", "tmp/compaction_messages.json"]:
    #     if os.path.exists(f):
    #         os.remove(f)

    model = get_model()
    logger = MessageLogger("tmp/compaction_messages.json")

    agent = Agent(
        model=model,
        tools=[generate_report, lookup_data],
        instructions=[
            "You are a helpful data analysis assistant.",
            "When asked to generate a report, use the generate_report tool.",
            "When asked to look up data, use the lookup_data tool.",
            "Always include the full tool output in your response.",
        ],
        enable_compaction=True,
        compaction_manager=CompactionManager(
            # Very low threshold so compaction triggers quickly for demo
            context_usage_threshold=0.10,
            context_reserve_tokens=1000,
            preserve_last_n_messages=2,
        ),
        db=SqliteDb(db_file="tmp/compaction_demo.db"),
        markdown=True,
    )

    # Patch model to log every LLM call
    patch_model_for_logging(model, logger)

    print("=" * 80)
    print("Conversation Compaction Demo")
    print("=" * 80)
    print(f"Model: {model.id} (context_window={model.context_window})")
    threshold = int(model.context_window * agent.compaction_manager.context_usage_threshold)
    print(f"Compaction threshold: {agent.compaction_manager.context_usage_threshold * 100}% (~{threshold} tokens)")
    print(f"Messages log: tmp/compaction_messages.json")
    print("=" * 80)

    benchmark_token_counting(model)

    questions = [
        "Generate a 5-page report on quantum computing trends",
        "Now look up 300 data records about 'AI adoption'",
        "What were the key findings from the report and data?",
    ]

    for i, question in enumerate(questions, 1):
        print(f"\n{'─' * 80}")
        print(f"Run {i}: {question}")
        print(f"{'─' * 80}")

        run_response = agent.run(question)

        compacted = run_response.compacted_run_ids
        total_messages = len(run_response.messages) if run_response.messages else 0
        msg_from_history = sum(1 for m in (run_response.messages or []) if getattr(m, "from_history", False))

        print(f"  Status: {run_response.status}")
        print(f"  Messages in response: {total_messages} (from history: {msg_from_history})")

        if run_response.metrics:
            print(f"  Tokens: input={run_response.metrics.input_tokens}, output={run_response.metrics.output_tokens}")

        if compacted:
            print(f"  ** COMPACTION TRIGGERED **")
            print(f"  Compacted run IDs: {compacted}")
            print(f"  Stats: {agent.compaction_manager.stats}")

        content = run_response.content or ""
        print(f"  Response: {(content[:200] + '...') if len(content) > 200 else content}")

    print(f"\n{'=' * 80}")
    print("Final Summary")
    print("=" * 80)
    stats = agent.compaction_manager.stats
    if stats and stats.get("compactions_performed", 0) > 0:
        print(f"  Compactions performed:  {stats.get('compactions_performed')}")
        print(f"  Messages before:        {stats.get('messages_before')}")
        print(f"  Messages after:         {stats.get('messages_after')}")
        print(f"  Tokens before:          {stats.get('tokens_before')}")
        print(f"  Tokens after:           {stats.get('tokens_after')}")
        print(f"  Tokens saved:           {stats.get('tokens_saved')}")
    else:
        print("  No compaction was triggered.")

    session_msgs = agent.get_session_messages()
    print(f"  Total messages in session: {len(session_msgs) if session_msgs else 0}")
    print(f"\n  Message log: tmp/compaction_messages.json ({len(logger.entries)} LLM calls logged)")
    print("\nDone.")
