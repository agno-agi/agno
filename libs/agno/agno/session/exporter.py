"""Session exporter helpers

Provides functions to export AgentSession/TeamSession objects to JSON, dict and
human-readable Markdown formats. This is intentionally small and conservative:
- it uses existing `.to_dict()` helpers where available
- it avoids inlining binary attachments (only metadata/filenames are exported)
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from agno.session.agent import AgentSession
from agno.utils.log import log_debug, log_warning


def export_session_to_dict(session: AgentSession, include_messages: bool = True) -> Dict[str, Any]:
    """Return a serializable dict representation of the session.

    This function tries to reuse existing `.to_dict()` implementations (for runs,
    summaries, etc.) and prunes or converts non-serializable values.
    """
    if session is None:
        return {}

    # Start with AgentSession.to_dict() which already handles many conversions
    try:
        session_dict = session.to_dict()
    except Exception as e:
        log_warning(f"Failed converting session to dict using to_dict(): {e}")
        # Fallback: manual shallow mapping
        session_dict = {
            "session_id": getattr(session, "session_id", None),
            "agent_id": getattr(session, "agent_id", None),
            "team_id": getattr(session, "team_id", None),
            "user_id": getattr(session, "user_id", None),
            "agent_data": getattr(session, "agent_data", None),
            "session_data": getattr(session, "session_data", None),
            "metadata": getattr(session, "metadata", None),
            "created_at": getattr(session, "created_at", None),
            "updated_at": getattr(session, "updated_at", None),
        }

    # Optionally remove messages content for very large sessions
    if not include_messages and session_dict.get("runs"):
        pruned_runs = []
        for run in session_dict.get("runs", []):
            run_copy = {k: v for k, v in run.items() if k != "messages"}
            pruned_runs.append(run_copy)
        session_dict["runs"] = pruned_runs

    # Ensure all nested objects are JSON serializable (best effort)
    try:
        json.dumps(session_dict)
    except TypeError:
        # Convert any objects by stringifying them (safe fallback)
        def _make_serializable(value: Any) -> Any:
            if isinstance(value, dict):
                return {k: _make_serializable(v) for k, v in value.items()}
            if isinstance(value, list):
                return [_make_serializable(v) for v in value]
            try:
                json.dumps(value)
                return value
            except TypeError:
                return str(value)

        session_dict = _make_serializable(session_dict)

    return session_dict


def export_session_to_json(session: AgentSession, path: Optional[str] = None, pretty: bool = True) -> str:
    """Return JSON string for the session; optionally write to `path` and return the path."""
    session_dict = export_session_to_dict(session)
    indent = 2 if pretty else None
    json_str = json.dumps(session_dict, indent=indent, ensure_ascii=False)
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json_str)
        log_debug(f"Wrote session export to {path}")
        return path
    return json_str


def export_session_to_markdown(session: AgentSession, path: Optional[str] = None, include_runs: bool = True) -> str:
    """Return a human-readable Markdown representation of the session.

    The Markdown includes basic metadata, an optional summary, and runs with
    messages. Attachments are represented by their metadata only.
    """
    if session is None:
        return ""

    lines = []
    lines.append(f"# Session {session.session_id}")
    if session.agent_id:
        lines.append(f"- Agent: `{session.agent_id}`")
    if session.user_id:
        lines.append(f"- User: `{session.user_id}`")
    if session.team_id:
        lines.append(f"- Team: `{session.team_id}`")
    if session.created_at:
        lines.append(f"- Created at: {session.created_at}")
    if session.updated_at:
        lines.append(f"- Updated at: {session.updated_at}")

    # Summary
    if session.summary is not None:
        lines.append("\n## Summary\n")
        if hasattr(session.summary, "summary"):
            lines.append(session.summary.summary)
        else:
            lines.append(str(session.summary))

    # Runs
    if include_runs and session.runs:
        lines.append("\n## Runs\n")
        for idx, run in enumerate(session.runs or [], start=1):
            run_id = getattr(run, "run_id", None)
            status = getattr(run, "status", None)
            lines.append(f"### Run {idx} — {run_id} — {status}")

            # messages: use available to_dict on messages
            messages = getattr(run, "messages", None)
            if messages:
                for m in messages:
                    role = getattr(m, "role", "")
                    content = getattr(m, "content", "")
                    # Show tool outputs concisely
                    lines.append(f"**{role}**: {content}")
            # Tool calls
            tool_calls = []
            if messages:
                for m in messages:
                    if getattr(m, "tool_calls", None):
                        for tc in m.tool_calls:
                            tool_calls.append(tc)
            if tool_calls:
                lines.append("\n**Tool calls:**")
                for tc in tool_calls:
                    lines.append(f"- {tc}")

    md = "\n".join(lines)
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(md)
        log_debug(f"Wrote session markdown to {path}")
        return path

    return md
