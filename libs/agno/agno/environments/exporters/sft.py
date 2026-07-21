"""Conversational-SFT JSONL export: one object per line, {"messages": [{"role", "content"}]}.

Tinker, Together, Fireworks and OpenAI all accept that core. They diverge on exactly
two axes -- tool representation and loss weighting -- and this exporter emits NEITHER,
so the file is portable by omission rather than by translation. Do not "helpfully" add
a `tools`, `weight`, or `trainable` key: the strictest checked consumer rejects the
entire file on any unknown key (strict set equality; it does not drop the key), so one
extra key breaks every consumer at once. Scores and fingerprints ride in the
`<path>.meta.json` sidecar, because provenance has nowhere else to live.
"""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agno.environments._engine import AttemptResult
from agno.environments.exporters._validate import MAX_CONVERSATIONS, MAX_DATASET_BYTES
from agno.environments.runner import EnvironmentRunResult


@dataclass
class ExportReport:
    """Where every candidate went. The counters sum to the candidate count -- scored
    attempts only; an unscored attempt is not a candidate under either value of
    only_passed."""

    n_written: int = 0
    n_skipped_failed: int = 0
    n_skipped_tool_runs: int = 0
    n_skipped_limit_hit: int = 0
    n_skipped_no_text: int = 0
    n_dropped_over_cap: int = 0


def _conversation_from(run: Any) -> Optional[List[Dict[str, str]]]:
    """The exportable conversation, or None when the run has no exportable text.

    Messages come from run.messages, excluding from_history entries, keeping roles
    {system, user, assistant} with non-empty string content. The system message is
    included -- it carries the format instructions that induced the output. The
    assistant text is the raw final assistant Message.content string, byte-for-byte
    what the model emitted: never a serialization of run.content, which under
    output_schema is a pydantic model whose str() and model_dump_json() both produce
    text the model never generated.
    """
    messages = [m for m in (run.messages or []) if not getattr(m, "from_history", False)]
    final_assistant_index = None
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "assistant":
            final_assistant_index = index
            break
    if final_assistant_index is None:
        return None
    final_content = messages[final_assistant_index].content
    if not isinstance(final_content, str) or not final_content.strip():
        return None
    conversation = [
        {"role": m.role, "content": m.content}
        for m in messages[: final_assistant_index + 1]
        if m.role in ("system", "user", "assistant") and isinstance(m.content, str) and m.content.strip()
    ]
    if not any(entry["role"] == "user" for entry in conversation):
        return None
    return conversation


def to_sft_jsonl(result: EnvironmentRunResult, path: Union[str, Path], *, only_passed: bool = True) -> ExportReport:
    """Write the result's exportable attempts as conversational-SFT JSONL.

    `only_passed=True` is the default because `learning_zone()` selects TASKS with
    both passed and failed attempts -- by construction those tasks contain failures,
    and exporting them would write wrong answers into a supervised file.
    `learning_zone()` selects tasks; `only_passed` selects attempts within them:
    SFT wants both.

    Emission order is task order, attempt order within -- deterministic under any
    concurrency. Caps match the strictest checked consumer: 320 conversations and
    1 MiB per file; over-cap rows are dropped from the tail in emission order and
    counted, never silently truncated.

    Selection effects are real: only_passed=True is rejection sampling, which
    amplifies what the model already does; exporting a full result overweights
    saturated tasks K-fold (which is why learning_zone() is the recommended input);
    and a judge floor inherits judge bias and compounds it across iterations.
    """
    report = ExportReport()
    lines: List[str] = []
    provenance: List[Dict[str, Any]] = []
    total_bytes = 0
    capped = False

    for task_result in result.task_results:
        for attempt_index, attempt in enumerate(task_result.attempts):
            candidate = _classify(attempt, only_passed=only_passed, report=report)
            if candidate is None:
                continue
            if capped:
                report.n_dropped_over_cap += 1
                continue
            line = json.dumps({"messages": candidate}, ensure_ascii=False)
            line_bytes = len(line.encode("utf-8")) + 1  # trailing newline
            if len(lines) >= MAX_CONVERSATIONS or total_bytes + line_bytes > MAX_DATASET_BYTES:
                capped = True
                report.n_dropped_over_cap += 1
                continue
            lines.append(line)
            total_bytes += line_bytes
            report.n_written += 1
            provenance.append(
                {
                    "task_id": task_result.task.id,
                    "attempt_index": attempt_index,
                    "score": attempt.score.value if attempt.score is not None else None,
                }
            )

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" disables platform newline translation: on Windows, translated CRLF
    # would silently push an exact-fit file past the byte cap and break the
    # sha256-pinned determinism.
    with open(output_path, "w", encoding="utf-8", newline="") as handle:
        handle.write("".join(line + "\n" for line in lines))

    sidecar = {
        "env_fingerprint": result.env_fingerprint,
        "policy_fingerprint": result.policy_fingerprint,
        "report": {
            "n_written": report.n_written,
            "n_skipped_failed": report.n_skipped_failed,
            "n_skipped_tool_runs": report.n_skipped_tool_runs,
            "n_skipped_limit_hit": report.n_skipped_limit_hit,
            "n_skipped_no_text": report.n_skipped_no_text,
            "n_dropped_over_cap": report.n_dropped_over_cap,
        },
        "options": {"only_passed": only_passed},
        "lines": provenance,
    }
    with open(str(output_path) + ".meta.json", "w", encoding="utf-8", newline="") as handle:
        handle.write(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n")
    return report


async def ato_sft_jsonl(
    result: EnvironmentRunResult, path: Union[str, Path], *, only_passed: bool = True
) -> ExportReport:
    """Async twin of to_sft_jsonl."""
    return await asyncio.to_thread(to_sft_jsonl, result, path, only_passed=only_passed)


def _classify(attempt: AttemptResult, *, only_passed: bool, report: ExportReport) -> Optional[List[Dict[str, str]]]:
    """Apply the skip checks in order, first match wins, exactly one counter per
    candidate. The rules overlap by construction (a limit-hit run is tool-bearing; a
    failed run can also have no text), so without this order the counters would
    double-count."""
    if attempt.score is None:
        return None  # not a candidate: unscored attempts never reach the exporter
    if only_passed and not attempt.score.passed:
        report.n_skipped_failed += 1
        return None
    if attempt.tool_call_limit_hit:
        # An answer produced after refused tool calls is an answer under duress.
        report.n_skipped_limit_hit += 1
        return None
    run = attempt.run
    if run is not None and run.tools:
        # The intersection format has no tool representation; emitting the final
        # answer without the tool trace that produced it would train the model to
        # answer WITHOUT the tools it actually used.
        report.n_skipped_tool_runs += 1
        return None
    conversation = _conversation_from(run) if run is not None else None
    if conversation is None:
        report.n_skipped_no_text += 1
        return None
    return conversation
