"""
Handing A Result To A Member
============================

Members share the leader's result store, and every member of a team runs under
the same session id. So a result id is a handle the whole team can use: the
leader can pass "res_..." to the next member in the task text instead of
pasting the payload, and that member reads it back itself.

This is what keeps a long team session flat. The report crosses the team once,
as a file, not once per handoff as text.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.offload import ResultStore
from agno.team import Team

db = SqliteDb(db_file="tmp/platform_handoff.db")


def read_incident_report(incident_id: str) -> str:
    """Read the full incident report.

    Args:
        incident_id: The incident to read.

    Returns:
        str: The report, one finding per line.
    """
    lines = [f"incident {incident_id}"]
    for i in range(1, 1201):
        severity = "critical" if i == 640 else "minor"
        lines.append(
            f"finding {i:05d} severity={severity} service=api-{i % 11} detail=timeout after {i % 90}s"
        )
    return "\n".join(lines)


platform_engineer = Agent(
    name="Platform Engineer",
    id="platform-engineer",
    role="Pulls incident reports",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[read_incident_report],
    instructions=dedent("""
        Pull the report. It arrives as a preview with a result id.
        Hand the result id back and say what the report covers.
        Never paste the report itself.
    """).strip(),
)

platform_manager = Agent(
    name="Platform Manager",
    id="platform-manager",
    role="Decides what to do about an incident",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=dedent("""
        You decide what the team does next.
        When a task gives you a result id, read it with read_result or
        search_result. Never ask for the text to be pasted to you.
    """).strip(),
)

platform_team = Team(
    name="Platform Team",
    id="platform-team",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    members=[platform_engineer, platform_manager],
    offload_tool_results=ResultStore(threshold_chars=8000),
    instructions=dedent("""
        You lead the platform team.
        A large member report arrives as a short preview with a result id.
        When you hand that report to another member, put the result id in the
        task and tell them to read it. Never paste the report into the task.
    """).strip(),
)


if __name__ == "__main__":
    platform_team.print_response(
        "Have the platform engineer pull incident INC-4417. "
        "Then have the platform manager read that same report and tell me the one critical finding.",
        session_id="platform-handoff",
        stream=True,
    )
