"""
Team Conversation Compaction Demo
==================================

Demonstrates automatic conversation compaction for a Team with multiple agents.

When the Team leader's conversation history (system + delegations + agent results)
approaches the context window limit, the entire history is summarised into a compact
message, drastically reducing token usage while preserving essential context.

Key insight: Team messages contain only the *final content* from member agents (not
their internal tool-call chains), but multiple rounds of delegation still accumulate
fast enough to trigger compaction.

Output files (in tmp/):
  team_compaction_messages.json  - Messages sent to Team leader LLM per call
  team_compaction_demo.db        - SQLite session storage

Setup (bash):
    export AGNO_MODEL_BASE_URL="http://your-server/v1"
    export AGNO_MODEL_API_KEY="sk-xxx"
    export AGNO_MODEL_ID="model_id"

Run:
    .venvs/demo/bin/python cookbook/03_teams/09_context_management/team_conversation_compaction.py
"""

import json
import os
import random
import string
from typing import Any, Dict, List, Optional, Type, Union

from agno.agent import Agent
from agno.compaction import CompactionManager
from agno.db.sqlite import SqliteDb
from agno.models.base import Model
from agno.models.message import Message
from agno.models.openai.like import OpenAILike
from agno.models.response import ModelResponse
from agno.team import Team
from agno.tools.function import Function


# ---------------------------------------------------------------------------
# Custom tools that generate long output to fill the context window
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


def analyze_metrics(dataset: str, dimensions: int = 200) -> str:
    """Analyze metrics for a dataset across multiple dimensions.

    Args:
        dataset: The dataset to analyze.
        dimensions: Number of metric dimensions to compute.
    """
    lines = [f"Metrics analysis for '{dataset}' ({dimensions} dimensions):\n"]
    for d in range(dimensions):
        metric_name = f"dim_{d:03d}"
        values = [round(random.uniform(0, 100), 2) for _ in range(10)]
        stats = {
            "name": metric_name,
            "mean": round(sum(values) / len(values), 2),
            "min": min(values),
            "max": max(values),
            "std": round(random.uniform(0.5, 15.0), 2),
            "p50": sorted(values)[5],
            "p95": sorted(values)[9],
            "trend": random.choice(["up", "down", "flat"]),
            "values": values,
        }
        lines.append(json.dumps(stats))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Model from env vars
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
    return OpenAILike(id=model_id, base_url=base_url, api_key=api_key)


# ---------------------------------------------------------------------------
# Message logger — same as agent demo, intercepts model.response() calls
# ---------------------------------------------------------------------------

class MessageLogger:
    """Captures every call to model.response() and dumps the messages."""

    def __init__(self, path: str):
        self.path = path
        self.entries: list = []

    def _serialise_messages(self, messages: List[Message]) -> list:
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


def patch_model_for_logging(model: Model, logger: MessageLogger, prefix: str = "") -> None:
    """Monkey-patch model.response / model.aresponse to log messages."""

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
            label=f"{prefix}LLM call #{_call_counter[0]}",
            messages=messages,
            extra={"tools_count": len(tools) if tools else 0},
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
            label=f"{prefix}LLM call #{_call_counter[0]} (async)",
            messages=messages,
            extra={"tools_count": len(tools) if tools else 0},
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
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    model = get_model()
    logger = MessageLogger("tmp/team_compaction_messages.json")

    # --- Define 3 specialist agents ---
    researcher = Agent(
        name="Researcher",
        model=model,
        tools=[generate_report],
        instructions=[
            "You are a research analyst. When asked, use generate_report to produce detailed reports.",
            "Return the full report content as your response.",
        ],
    )

    data_analyst = Agent(
        name="DataAnalyst",
        model=model,
        tools=[lookup_data],
        instructions=[
            "You are a data analyst. When asked, use lookup_data to retrieve datasets.",
            "Return a summary of the data you found.",
        ],
    )

    metrics_analyst = Agent(
        name="MetricsAnalyst",
        model=model,
        tools=[analyze_metrics],
        instructions=[
            "You are a metrics specialist. When asked, use analyze_metrics to compute metrics.",
            "Return a summary of the metrics analysis.",
        ],
    )

    # --- Define the Team with compaction enabled ---
    team = Team(
        name="AnalysisTeam",
        model=model,
        members=[researcher, data_analyst, metrics_analyst],
        mode="coordinate",
        instructions=[
            "You are the team leader coordinating research, data lookup, and metrics analysis.",
            "Delegate tasks to the appropriate specialist agents.",
            "After receiving results from agents, provide a brief synthesis.",
        ],
        enable_compaction=True,
        compaction_manager=CompactionManager(
            # Low threshold for demo — triggers after ~2 rounds of delegation
            context_usage_threshold=0.10,
            context_reserve_tokens=1000,
            preserve_last_n_messages=2,
        ),
        db=SqliteDb(db_file="tmp/team_compaction_demo.db"),
        markdown=True,
    )

    # Patch the team leader's model to log every LLM call
    # Note: member agents share the same model instance, so all calls are logged
    patch_model_for_logging(model, logger, prefix="[Team] ")

    print("=" * 80)
    print("Team Conversation Compaction Demo")
    print("=" * 80)
    print(f"Model: {model.id} (context_window={model.context_window})")
    print(f"Members: {[m.name for m in team.members]}")
    threshold = int(model.context_window * team.compaction_manager.context_usage_threshold)
    print(f"Compaction threshold: {team.compaction_manager.context_usage_threshold * 100}% (~{threshold} tokens)")
    print("Messages log: tmp/team_compaction_messages.json")
    print("=" * 80)

    # --- Multi-round questions that generate large delegation results ---
    questions = [
        # Round 1: delegate to researcher (generates large report content)
        "Please have the Researcher generate a 5-page report on quantum computing trends.",

        # Round 2: delegate to data analyst (generates large lookup result)
        # Team history now includes Round 1's full system + delegation + result
        "Please have the DataAnalyst look up 300 records about AI adoption.",

        # Round 3: delegate to metrics analyst (another large result)
        # Team history now includes Rounds 1+2 — should be near threshold
        "Please have the MetricsAnalyst analyze metrics for 'global_warming_impact' with 200 dimensions.",

        # Round 4: synthesis question — this should trigger compaction
        # because Rounds 1-3 history exceeds the threshold
        "Summarize the key findings from all three analyses we've done so far.",
    ]

    for i, question in enumerate(questions, 1):
        print(f"\n{'─' * 80}")
        print(f"Run {i}: {question}")
        print(f"{'─' * 80}")

        run_response = team.run(question)

        compacted = run_response.compacted_run_ids
        total_messages = len(run_response.messages) if run_response.messages else 0
        msg_from_history = sum(1 for m in (run_response.messages or []) if getattr(m, "from_history", False))

        print(f"  Status: {run_response.status}")
        print(f"  Messages in response: {total_messages} (from history: {msg_from_history})")

        if run_response.metrics:
            print(f"  Tokens: input={run_response.metrics.input_tokens}, output={run_response.metrics.output_tokens}")

        if run_response.member_responses:
            for mr in run_response.member_responses:
                agent_name = getattr(mr, "agent_name", "unknown")
                content_len = len(mr.content) if mr.content else 0
                print(f"  Member '{agent_name}': {content_len:,} chars")

        if compacted:
            print("  ** COMPACTION TRIGGERED **")
            print(f"  Compacted run IDs: {compacted}")
            print(f"  Stats: {team.compaction_manager.stats}")

        content = run_response.content or ""
        print(f"  Response: {(content[:200] + '...') if len(content) > 200 else content}")

    print(f"\n{'=' * 80}")
    print("Final Summary")
    print("=" * 80)
    stats = team.compaction_manager.stats
    if stats and stats.get("compactions_performed", 0) > 0:
        print(f"  Compactions performed:  {stats.get('compactions_performed')}")
        print(f"  Messages before:        {stats.get('messages_before')}")
        print(f"  Messages after:         {stats.get('messages_after')}")
        print(f"  Tokens before:          {stats.get('tokens_before')}")
        print(f"  Tokens after:           {stats.get('tokens_after')}")
        print(f"  Tokens saved:           {stats.get('tokens_saved')}")
    else:
        print("  No compaction was triggered.")

    session_msgs = team.get_session_messages()
    print(f"  Total messages in session: {len(session_msgs) if session_msgs else 0}")
    print(f"\n  Message log: tmp/team_compaction_messages.json ({len(logger.entries)} LLM calls logged)")
    print("\nDone.")
