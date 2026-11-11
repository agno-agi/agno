"""A compact account of what a Task attempt did, read from its run when asked.

The worker's reply says what it found; this lists what it ran, from the run itself: commands and
other tool calls with their inputs and whether they failed, workflow steps, files and the
checked-out commit. Nothing is inferred and nothing is stored: the run stays the one source, read
through `GET /company/runs/{run_id}`. Outputs are left out so a summary fits a model's context.

The Task's own `evidence` field is unrelated: it holds the Source intake records a Task was
proposed from.
"""

import json
from typing import Any, Dict, List, Optional, Tuple

# Harness tools whose input is a shell command.
_COMMAND_TOOLS = {"bash": "command", "shell": "command"}
MAX_ITEMS = 20
MAX_INPUT = 300
NO_EVIDENCE = "The run recorded no commands, tool calls, workflow steps or files."


def _clip(value: Any, limit: int) -> Optional[str]:
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + f"... [{len(text) - limit} more characters]"


def _tool_item(tool: Dict[str, Any], member: Optional[str] = None) -> Dict[str, Any]:
    name = str(tool.get("tool_name") or "tool")
    args = tool.get("tool_args") or {}
    command_key = _COMMAND_TOOLS.get(name.lower())
    command = args.get(command_key) if command_key and isinstance(args, dict) else None
    item: Dict[str, Any] = {
        "kind": "command" if command is not None else "tool",
        "name": name,
        # A tool called without arguments has no input worth showing.
        "input": _clip(command if command is not None else (args or None), MAX_INPUT),
        "error": bool(tool.get("tool_call_error")),
    }
    if member:
        item["member"] = member
    return item


def run_evidence(run: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """What the run recorded, without outputs, and a note when there is none or some were left out."""
    items: List[Dict[str, Any]] = []
    for tool in run.get("tools") or []:
        if isinstance(tool, dict):
            items.append(_tool_item(tool))
    for member in run.get("member_responses") or []:
        if isinstance(member, dict):
            owner = member.get("agent_id") or member.get("team_id")
            items.extend(_tool_item(tool, owner) for tool in member.get("tools") or [] if isinstance(tool, dict))
    for step in run.get("step_results") or []:
        if isinstance(step, dict):
            items.append(
                {"kind": "step", "name": step.get("step_name") or "step", "error": step.get("success") is False}
            )
    for file in run.get("files") or []:
        if isinstance(file, dict):
            items.append({"kind": "file", "name": file.get("filename") or file.get("name") or file.get("id")})
    repository = ((run.get("metadata") or {}).get("sandbox") or {}).get("repository")
    if isinstance(repository, dict) and repository.get("commit"):
        items.append(
            {
                "kind": "checkout",
                "name": repository.get("url"),
                "input": f"{repository.get('branch')}@{repository['commit']}",
            }
        )
    if not items:
        return [], NO_EVIDENCE
    if len(items) <= MAX_ITEMS:
        return items, None
    note = f"Showing the first {MAX_ITEMS} of {len(items)} recorded items; the rest are in the run."
    return items[:MAX_ITEMS], note
