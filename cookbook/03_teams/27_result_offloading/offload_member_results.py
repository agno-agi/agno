"""
Offload Member Results
======================

A member's answer reaches the team leader as the result of the delegation
tool, so it is the payload that grows a team session. With
offload set, the leader's transcript holds a short envelope with
a result id, and the full answer is stored as a file the leader can read back.

Run this and compare the printed transcript size with the size of the reports
the members actually produced.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.offload import ResultStore
from agno.team import Team

db = SqliteDb(db_file="tmp/platform_team.db")


# ---------------------------------------------------------------------------
# A tool with a large, boring payload: the kind of thing a member reads and
# the leader should never have to hold.
# ---------------------------------------------------------------------------
def read_deployment_log(service: str) -> str:
    """Read the full deployment log for one service.

    Args:
        service: The service name.

    Returns:
        str: The log, one line per event.
    """
    lines = []
    for i in range(1, 1501):
        status = "ERROR connection refused" if i == 1180 else "ok"
        lines.append(
            f"{service} event {i:05d} worker-{i % 7} latency={i % 250}ms {status}"
        )
    return "\n".join(lines)


def list_platform_components() -> str:
    """List every component running on the platform.

    Returns:
        str: One component per line, with its owner and version.
    """
    return "\n".join(
        f"component-{i:04d} owner=team-{i % 9} version=1.{i % 40}.{i % 12}"
        for i in range(1, 1201)
    )


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
platform_builder = Agent(
    name="Platform Builder",
    id="platform-builder",
    role="Builds new components on the platform",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[list_platform_components],
    instructions=dedent("""
        You build and inventory platform components.
        A large tool result arrives as a preview with a result id. Use
        search_result to count and find what you need, then report the
        components and counts that answer the task.
    """).strip(),
)

platform_manager = Agent(
    name="Platform Manager",
    id="platform-manager",
    role="Owns platform health and ownership",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[list_platform_components],
    instructions=dedent("""
        You track who owns what and which versions are running.
        A large tool result arrives as a preview with a result id. Use
        search_result to find the owners you were asked about, then report
        them with their versions.
    """).strip(),
)

platform_engineer = Agent(
    name="Platform Engineer",
    id="platform-engineer",
    role="Diagnoses deployments and incidents",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[read_deployment_log],
    instructions=dedent("""
        You read deployment logs and find what broke.
        A large log arrives as a preview with a result id. Use search_result
        to find the failing events, then read_result around them, and quote
        the failing line with the lines on either side.
    """).strip(),
)

# ---------------------------------------------------------------------------
# The team leader
#
# offload=True uses the 4000 character default. A ResultStore sets the
# threshold and the rest. Members run on the leader's store, so a member can
# read back a result another member produced.
# ---------------------------------------------------------------------------
platform_team = Team(
    name="Platform Team",
    id="platform-team",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    members=[platform_builder, platform_manager, platform_engineer],
    offload=ResultStore(threshold=2000),
    add_history_to_context=True,
    num_history_runs=5,
    instructions=dedent("""
        You lead the platform team.
        Delegate to the right member, then answer from what they report.
        A large member report arrives as a short preview with a result id.
        Use search_result to find what you need and read_result to read it.
    """).strip(),
)


def report_transcript_size(session_id: str) -> None:
    """Print how much of the leader's transcript each tool result takes."""
    run = platform_team.get_last_run_output(session_id=session_id)
    print("\nLeader transcript")
    total = 0
    for message in run.messages or []:
        size = len(message.content or "")
        total += size
        if message.role == "tool":
            print(f"  tool {message.tool_name}: {size} characters")
    print(f"  total: {total} characters")


if __name__ == "__main__":
    session_id = "platform-session"

    platform_team.print_response(
        "Ask the platform engineer for the deployment log of the checkout service, "
        "then tell me which event failed and what it says.",
        session_id=session_id,
        stream=True,
    )
    report_transcript_size(session_id)

    platform_team.print_response(
        "Now ask the platform builder for the full component inventory, "
        "then tell me how many components team-3 owns.",
        session_id=session_id,
        stream=True,
    )
    report_transcript_size(session_id)

    print("\nStored results for this session")
    for ref in platform_team._result_store.live_ids(session_id):
        print(
            f"  {ref.result_id} from {ref.tool_name}: {ref.line_count} lines, {ref.size_bytes} bytes"
        )
