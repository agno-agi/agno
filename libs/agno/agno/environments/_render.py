"""The rollout grid. Private: `summary()` is the programmatic contract, this is not.

K attempts is K glyphs: a full block for a pass, a light shade for a scored fail, a
triangle for an unscored attempt. Rendered live through rich during a TTY run, and
statically by `EnvRunResult.__str__`.
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
        # Only when a provider actually reported cost; a bundled price table would be
        # silently wrong within a quarter.
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
