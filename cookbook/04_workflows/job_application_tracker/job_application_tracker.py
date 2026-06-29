"""
Job Application Tracker Workflow
=================================
A practical agentic workflow that demonstrates:
- Custom tools for structured data entry
- Pydantic models for typed input/output
- SQLite storage for session persistence across runs
- Multi-step workflow with an orchestrator agent

Run:
    python cookbook/04_workflows/job_application_tracker/job_application_tracker.py

Try these prompts:
    - "Track this job: Software Engineer at Google, https://careers.google.com/jobs/123, applied via LinkedIn"
    - "Show me all my applications"
    - "Update the status of my Google application to Interview Scheduled"
    - "How many jobs have I applied to?"
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from agno.agent import Agent
from agno.models.google import Gemini
from agno.storage.sqlite import SqliteStorage
from agno.tools import tool
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class JobApplication(BaseModel):
    """Structured representation of a job application."""

    company: str = Field(..., description="Company name")
    role: str = Field(..., description="Job title / role")
    url: Optional[str] = Field(None, description="Job posting URL")
    source: Optional[str] = Field(None, description="Where you found it (LinkedIn, Naukri, etc.)")
    status: str = Field(
        default="Applied",
        description="Current status: Applied | Interview Scheduled | Rejected | Offer | Withdrawn",
    )
    applied_at: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d"),
        description="Date applied (YYYY-MM-DD)",
    )
    notes: Optional[str] = Field(None, description="Any extra notes")


# ---------------------------------------------------------------------------
# SQLite helpers  (plain sqlite3 — no extra dependencies)
# ---------------------------------------------------------------------------

DB_PATH = Path("tmp/job_tracker.db")


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS applications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company     TEXT    NOT NULL,
            role        TEXT    NOT NULL,
            url         TEXT,
            source      TEXT,
            status      TEXT    NOT NULL DEFAULT 'Applied',
            applied_at  TEXT    NOT NULL,
            notes       TEXT
        )
        """
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Custom tools
# ---------------------------------------------------------------------------

@tool
def add_application(
    company: str,
    role: str,
    url: Optional[str] = None,
    source: Optional[str] = None,
    status: str = "Applied",
    notes: Optional[str] = None,
) -> str:
    """
    Save a new job application to the tracker.

    Args:
        company: Company name.
        role:    Job title.
        url:     Link to the job posting (optional).
        source:  Where you found the job, e.g. LinkedIn, Naukri (optional).
        status:  Application status (default: Applied).
        notes:   Any additional notes (optional).

    Returns:
        Confirmation message with the assigned ID.
    """
    app = JobApplication(
        company=company,
        role=role,
        url=url,
        source=source,
        status=status,
        notes=notes,
    )
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO applications (company, role, url, source, status, applied_at, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (app.company, app.role, app.url, app.source, app.status, app.applied_at, app.notes),
    )
    conn.commit()
    conn.close()
    return f"✅ Saved! Application #{cur.lastrowid} — {app.role} at {app.company} ({app.status})"


@tool
def list_applications(status_filter: Optional[str] = None) -> str:
    """
    List all tracked job applications, optionally filtered by status.

    Args:
        status_filter: Optional status to filter by (e.g. 'Applied', 'Interview Scheduled').

    Returns:
        JSON string of matching applications.
    """
    conn = _get_conn()
    if status_filter:
        rows = conn.execute(
            "SELECT * FROM applications WHERE status = ? ORDER BY applied_at DESC",
            (status_filter,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM applications ORDER BY applied_at DESC"
        ).fetchall()
    conn.close()

    if not rows:
        return "No applications found."

    results = [dict(r) for r in rows]
    return json.dumps(results, indent=2)


@tool
def update_status(application_id: int, new_status: str) -> str:
    """
    Update the status of an existing application.

    Args:
        application_id: The numeric ID of the application (from list_applications).
        new_status:     New status string, e.g. 'Interview Scheduled', 'Offer', 'Rejected'.

    Returns:
        Confirmation or error message.
    """
    valid = {"Applied", "Interview Scheduled", "Rejected", "Offer", "Withdrawn"}
    if new_status not in valid:
        return f"❌ Invalid status '{new_status}'. Choose from: {', '.join(sorted(valid))}"

    conn = _get_conn()
    cur = conn.execute(
        "UPDATE applications SET status = ? WHERE id = ?",
        (new_status, application_id),
    )
    conn.commit()
    conn.close()

    if cur.rowcount == 0:
        return f"❌ No application found with ID {application_id}."
    return f"✅ Application #{application_id} updated to '{new_status}'."


@tool
def get_summary() -> str:
    """
    Return a summary count of applications grouped by status.

    Returns:
        Human-readable summary string.
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT status, COUNT(*) as count FROM applications GROUP BY status"
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    conn.close()

    if total == 0:
        return "No applications tracked yet. Start by adding one!"

    lines = [f"📊 Job Application Summary ({total} total):", ""]
    for row in rows:
        lines.append(f"  • {row['status']}: {row['count']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

tracker_agent = Agent(
    name="Job Application Tracker",
    model=Gemini(id="gemini-2.0-flash"),
    tools=[add_application, list_applications, update_status, get_summary],
    storage=SqliteStorage(table_name="tracker_sessions", db_file="tmp/tracker_sessions.db"),
    # Persist conversation across runs so the agent remembers context
    add_history_to_messages=True,
    num_history_runs=6,
    instructions=[
        "You are a helpful job application tracking assistant.",
        "When a user wants to track a job, extract company, role, URL, and source then call add_application.",
        "When listing applications, format the JSON response as a clean readable table.",
        "Always confirm actions clearly and suggest next steps.",
        "If the user asks for a summary, call get_summary.",
    ],
    markdown=True,
    show_tool_calls=True,
)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  Job Application Tracker — powered by Agno")
    print("  Type 'exit' to quit, 'summary' for stats")
    print("=" * 60)
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "bye"}:
            print("Goodbye! Good luck with your applications 🚀")
            break

        tracker_agent.print_response(user_input, stream=True)
        print()
