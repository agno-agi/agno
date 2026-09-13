"""
Job Application Tracker
=======================

Demonstrates combining structured output extraction with agent tool calls that
persist job applications in workflow session state across runs.
"""

from datetime import datetime
from typing import Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.run import RunContext
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/job_application_tracker.db")

VALID_STATUSES = ["Applied", "Interview Scheduled", "Rejected", "Offer", "Withdrawn"]


# ---------------------------------------------------------------------------
# Define Structured Models
# ---------------------------------------------------------------------------
class JobApplication(BaseModel):
    """Structured representation of a single job application."""

    company: str = Field(..., description="Company name")
    role: str = Field(..., description="Job title / role")
    url: Optional[str] = Field(None, description="Job posting URL")
    source: Optional[str] = Field(
        None, description="Where the job was found, e.g. a job board"
    )
    status: str = Field(
        default="Applied",
        description=f"Application status, one of: {', '.join(VALID_STATUSES)}",
    )
    notes: Optional[str] = Field(None, description="Any extra notes")


# ---------------------------------------------------------------------------
# Define Session-State Tools
# ---------------------------------------------------------------------------
def save_application(
    run_context: RunContext,
    company: str,
    role: str,
    status: str = "Applied",
    url: str = "",
    source: str = "",
    notes: str = "",
) -> str:
    if run_context.session_state is None:
        run_context.session_state = {}

    applications = run_context.session_state.setdefault("applications", [])
    record = {
        "id": len(applications) + 1,
        "company": company,
        "role": role,
        "status": status,
        "url": url,
        "source": source,
        "notes": notes,
        "applied_at": datetime.now().strftime("%Y-%m-%d"),
    }
    applications.append(record)
    return f"Saved application #{record['id']}: {role} at {company} ({status})."


def list_applications(run_context: RunContext) -> str:
    if run_context.session_state is None:
        run_context.session_state = {}

    applications = run_context.session_state.get("applications", [])
    if len(applications) == 0:
        return "No applications tracked yet."

    lines = [
        f"#{app['id']} {app['role']} at {app['company']} - {app['status']}"
        for app in applications
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
extractor_agent = Agent(
    name="Application Extractor",
    model=OpenAIResponses(id="gpt-5.5"),
    output_schema=JobApplication,
    instructions=[
        "Extract a single job application from the user's message.",
        "Infer the company, role, URL and source when they are present.",
        f"Set status to one of: {', '.join(VALID_STATUSES)}. Default to 'Applied'.",
    ],
)

tracker_agent = Agent(
    name="Application Tracker",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[save_application, list_applications],
    instructions=[
        "You receive a structured job application.",
        "Call save_application exactly once with its fields.",
        "Then call list_applications and show the full tracker to the user.",
    ],
)

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
extract_application_step = Step(
    name="extract_application",
    description="Extract a structured job application from the message",
    agent=extractor_agent,
)

save_application_step = Step(
    name="save_application",
    description="Save the application to the tracker and list all applications",
    agent=tracker_agent,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
job_application_workflow = Workflow(
    name="Job Application Tracker",
    db=db,
    steps=[extract_application_step, save_application_step],
    session_state={"applications": []},
    # A fixed session id keeps the tracked applications across separate runs.
    session_id="job_tracker_demo",
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Example 1: Track a Backend Engineer role ===")
    job_application_workflow.print_response(
        input="Applied to a Backend Engineer role at Acme Robotics via a job board, https://acme.example/careers/123"
    )
    print("Workflow session state:", job_application_workflow.get_session_state())

    print("\n=== Example 2: Track a Python Developer role ===")
    job_application_workflow.print_response(
        input="Got an interview scheduled for a Python Developer position at Globex, found via a referral"
    )
    print("Workflow session state:", job_application_workflow.get_session_state())

    print("\n=== Example 3: Track a Data Scientist role ===")
    job_application_workflow.print_response(
        input="Submitted an application for a Data Scientist role at Initech"
    )
    print("Final workflow session state:", job_application_workflow.get_session_state())
