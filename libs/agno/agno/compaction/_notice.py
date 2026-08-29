"""The survival notice: durable state that outlives a compaction pass.

Generated at pass time and pinned to the record — a per-call-fresh notice would invalidate the
prompt-cache prefix on every offloading tool batch, and the staleness cost is bounded (results
offloaded after the pass are still inline in the kept tail).
"""

from dataclasses import dataclass, field
from typing import List

NOTICE_OPEN_TAG = "<context_survived>"
NOTICE_CLOSE_TAG = "</context_survived>"

_MAX_RESULT_IDS = 100
_MAX_VARIABLES = 200
_MAX_FILES = 100


@dataclass
class NoticeInputs:
    """Probed durable state; every source is optional and defensively collected."""

    result_ids: List[str] = field(default_factory=list)  # offloaded results readable via read_result
    variables: List[str] = field(default_factory=list)  # live CodeMode variables
    files: List[str] = field(default_factory=list)  # session filesystem paths


def _capped(values: List[str], cap: int) -> str:
    shown = ", ".join(values[:cap])
    overflow = len(values) - cap
    if overflow > 0:
        shown += f" (+{overflow} more)"
    return shown


def build_survival_notice(inputs: NoticeInputs) -> str:
    """The <context_survived> block, or an empty string when no source has anything."""
    lines: List[str] = []
    if inputs.result_ids:
        lines.append(f"- Offloaded results readable with read_result(id): {_capped(inputs.result_ids, _MAX_RESULT_IDS)}")
    if inputs.variables:
        lines.append(f"- CodeMode variables still defined: {_capped(inputs.variables, _MAX_VARIABLES)}")
    if inputs.files:
        lines.append(f"- Files: {_capped(inputs.files, _MAX_FILES)}")
    if not lines:
        return ""
    body = "\n".join(lines)
    return (
        f"{NOTICE_OPEN_TAG}\n"
        "Earlier conversation was compacted into the summary above. State that survived in full:\n"
        f"{body}\n"
        "Reuse these instead of recomputing them.\n"
        f"{NOTICE_CLOSE_TAG}"
    )
