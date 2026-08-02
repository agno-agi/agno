"""The rollout grid and the per-attempt report. Private: `summary()` is the
programmatic contract, none of this is.

K attempts is K glyphs: a full block for a pass, a light shade for a scored fail, a
triangle for an unscored attempt. Rendered live through rich during a TTY run, and
statically by `EnvironmentRunResult.__str__`. `build_report` is the layer underneath the
glyphs: one text block per attempt -- verdict, score reason, tool executions, the
answer -- so a red glyph is explainable without walking the result objects by hand.
"""

from typing import Any, Dict, List, Optional, Sequence

PASS_GLYPH = "█"  # full block
FAIL_GLYPH = "░"  # light shade
UNSCORED_GLYPH = "▲"  # triangle


def attempt_glyph(score: Optional[Any]) -> str:
    if score is None:
        return UNSCORED_GLYPH
    return PASS_GLYPH if score.passed else FAIL_GLYPH


def build_grid(
    env_name: str,
    k: int,
    rows: Sequence[Dict[str, Any]],
    *,
    n_attempts: int,
    duration_seconds: float,
    total_cost: Optional[float] = None,
    first_error: Optional[str] = None,
    stopped_early: Optional[str] = None,
) -> str:
    """The static grid. Each row: {id, glyphs, n_passed, n_scored, pass_rate,
    learning_zone, n_unscored}."""
    header = f"{env_name}                 k={k} · {n_attempts} attempts · {round(duration_seconds)}s"
    if total_cost is not None:
        # Only when a provider actually reported cost; no price table is bundled.
        header += f" · ${total_cost:.4f}"

    id_width = max([len(str(row["id"])) for row in rows], default=2)
    lines = [header]
    for row in rows:
        rate = f"{row['pass_rate']:.2f}" if row["pass_rate"] is not None else "-"
        line = f"  {str(row['id']):<{id_width}}   {row['glyphs']:<{k}}   {row['n_passed']}/{row['n_scored']}   {rate}"
        tags: List[str] = []
        if row.get("learning_zone"):
            tags.append("learning zone")
        if row.get("n_unscored"):
            tags.append(f"{row['n_unscored']} unscored")
        if tags:
            line += "   " + "   ".join(tags)
        lines.append(line)
    if stopped_early:
        lines.append(f"  stopped early: {stopped_early}")
    if first_error:
        lines.append(f"  first error: {first_error}")
    return "\n".join(lines)


def _clip(text: Any, limit: int) -> str:
    """One line, whitespace collapsed, hard-capped at `limit` characters."""
    flat = " ".join(str(text).split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 3] + "..."


def _attempt_lines(attempt: Any, index: int) -> List[str]:
    """The report block for one attempt. `index` is 1-based, matching glyph order."""
    score = attempt.score
    verdict = "unscored" if score is None else ("PASS" if score.passed else "FAIL")
    value = f"{score.value:.2f}" if score is not None else "-"
    head = (
        f"  attempt {index}: {verdict}   value={value}   "
        f"stop={attempt.stop_reason.value}   {attempt.duration_seconds:.1f}s"
    )
    if attempt.tool_call_limit_hit:
        head += "   tool-call limit hit"
    lines = [head]
    if attempt.error:
        lines.append(f"    error: {_clip(attempt.error, 200)}")
    if score is not None and score.reason:
        lines.append(f"    reason: {_clip(score.reason, 200)}")
    run = attempt.run
    if run is None:
        lines.append("    (no run captured)")
        return lines
    for tool in getattr(run, "tools", None) or []:
        status = "error" if tool.tool_call_error else "ok"
        lines.append(f"    tool: {tool.tool_name}({tool.tool_args}) -> {status}")
    if run.content is not None:
        lines.append(f"    answer: {_clip(run.content, 110)}")
    metrics = getattr(run, "metrics", None)
    if metrics is not None:
        tokens = f"    tokens: in={metrics.input_tokens} out={metrics.output_tokens}"
        cost = getattr(metrics, "cost", None)
        if cost is not None:
            tokens += f" cost=${cost:.4f}"
        lines.append(tokens)
    return lines


def _is_reportable_failure(attempt: Any) -> bool:
    """A "red": scored-and-failed, or any attempt that did not complete cleanly."""
    if attempt.score is not None:
        return not attempt.score.passed
    return True  # unscored: error, timeout, cancellation, pause, or scorer crash


def build_report(
    task_results: Sequence[Any],
    *,
    only: str = "failed",
    attempts: Optional[int] = None,
) -> str:
    """The per-attempt report. Presentation only -- the format is not a contract and
    may change without notice; parse `summary()` or `save()` output, never this.

    `only="failed"` (default) keeps the attempts a person investigates: scored fails
    plus everything unscored (errors, timeouts, pauses). `only="all"` shows every
    attempt. `attempts` caps the rows shown per task after filtering.
    """
    if only not in ("failed", "all"):
        raise ValueError(f"only must be 'failed' or 'all', got {only!r}")
    sections: List[str] = []
    n_total = 0
    for task_result in task_results:
        n_total += len(task_result.attempts)
        selected = [
            (index, attempt)
            for index, attempt in enumerate(task_result.attempts, start=1)
            if only == "all" or _is_reportable_failure(attempt)
        ]
        hidden = 0
        if attempts is not None and len(selected) > attempts:
            hidden = len(selected) - attempts
            selected = selected[:attempts]
        if not selected:
            continue
        lines = [f"task {task_result.task.id}: {_clip(task_result.task.input, 90)}"]
        for index, attempt in selected:
            lines.extend(_attempt_lines(attempt, index))
        if hidden:
            lines.append(f"  ... {hidden} more (raise attempts= to see them)")
        sections.append("\n".join(lines))
    if not sections:
        return f'all {n_total} attempts passed; nothing to report. print_report(only="all") shows every attempt.'
    return "\n\n".join(sections)


class LiveGrid:
    """One rich Live, updated from the engine's per-attempt completion callback."""

    def __init__(self, console: Any, env_name: str, k: int, task_ids: Sequence[str]) -> None:
        from rich.live import Live

        self._env_name = env_name
        self._k = k
        self._task_ids = list(task_ids)
        self._slots: List[List[Optional[Any]]] = [[None] * k for _ in task_ids]
        self._filled: List[List[bool]] = [[False] * k for _ in task_ids]
        self._n_done = 0
        self._live = Live(console=console, refresh_per_second=8)

    def __enter__(self) -> "LiveGrid":
        self._live.__enter__()
        self._refresh()
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self._live.__exit__(*exc_info)

    def on_attempt(self, input_index: int, attempt_index: int, attempt: Any) -> None:
        self._slots[input_index][attempt_index] = attempt
        self._filled[input_index][attempt_index] = True
        self._n_done += 1
        self._refresh()

    def _refresh(self) -> None:
        from rich.text import Text

        rows = []
        for task_index, task_id in enumerate(self._task_ids):
            glyphs = ""
            n_passed = 0
            n_scored = 0
            n_unscored = 0
            for attempt_index in range(self._k):
                attempt = self._slots[task_index][attempt_index]
                if not self._filled[task_index][attempt_index] or attempt is None:
                    glyphs += " "
                    continue
                glyphs += attempt_glyph(attempt.score)
                if attempt.score is None:
                    n_unscored += 1
                else:
                    n_scored += 1
                    if attempt.score.passed:
                        n_passed += 1
            rows.append(
                {
                    "id": task_id,
                    "glyphs": glyphs,
                    "n_passed": n_passed,
                    "n_scored": n_scored,
                    "pass_rate": (n_passed / n_scored) if n_scored else None,
                    "learning_zone": False,  # settled after the run; too noisy mid-flight
                    "n_unscored": n_unscored,
                }
            )
        text = build_grid(
            self._env_name,
            self._k,
            rows,
            n_attempts=len(self._task_ids) * self._k,
            duration_seconds=0.0,
        )
        # Drop the static header's duration (it reads 0s mid-run) in favor of progress.
        body = text.split("\n", 1)
        header = (
            f"{self._env_name}                 k={self._k} · {self._n_done}/{len(self._task_ids) * self._k} attempts"
        )
        self._live.update(Text(header + ("\n" + body[1] if len(body) > 1 else "")))
