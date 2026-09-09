"""
Member Store Settings
=====================

`offload_tool_results` on a member has three states inside a team:

- unset (the default): the member inherits the team's store, so its results
  and its stored history use the team's settings and are readable by the
  whole team;
- `False`: the member stays out. Its tool results are never offloaded and
  its stored history keeps the whole text, since it has no read-back tools;
- a `ResultStore(...)`: the member keeps its own threshold and preview, bound
  to the team's database so its results stay reachable from the rest of the
  team. A db or fs named on a member store is not used; payloads go where
  the whole team can read them.

The team's own setting is never written onto a member, and the binding is
redone every time the team initializes, so a member moved to another team
follows that team.

This example runs one team with a member in each state and prints what each
one's store looks like and what its stored history holds.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.offload import ResultStore
from agno.team import Team

db = SqliteDb(db_file="tmp/member_store_settings.db")


def read_metrics(service: str) -> str:
    """Read a service's metrics for the last hour.

    Args:
        service: The service name.

    Returns:
        str: One sample per line.
    """
    return "\n".join(
        f"{service} t+{i:04d}s cpu={i % 100}% mem={200 + i % 300}MB errors={1 if i % 211 == 0 else 0}"
        for i in range(1, 1201)
    )


def make_member(name: str, member_id: str, **settings) -> Agent:
    return Agent(
        name=name,
        id=member_id,
        role="Reads service metrics and reports on them",
        model=OpenAIResponses(id="gpt-5.5"),
        tools=[read_metrics],
        instructions=dedent("""
            Read the metrics you are asked about and report the number of
            samples with errors. Quote two of the error lines.
        """).strip(),
        **settings,
    )


inheriting = make_member("Inheriting Member", "inheriting")
opted_out = make_member("Opted Out Member", "opted-out", offload_tool_results=False)
own_settings = make_member(
    "Own Settings Member",
    "own-settings",
    offload_tool_results=ResultStore(
        threshold_chars=4000, preview_lines=2, preview_chars=120
    ),
)

# ---------------------------------------------------------------------------
# The team
# ---------------------------------------------------------------------------
team = Team(
    name="Metrics Team",
    id="metrics-team",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    members=[inheriting, opted_out, own_settings],
    offload_tool_results=ResultStore(threshold_chars=8000),
    instructions=dedent("""
        You lead the metrics team. Delegate each service to the member named
        for it, then summarize the error counts.
    """).strip(),
)


def describe_member(member: Agent) -> None:
    store = member.result_store
    if store is None:
        print(f"   {member.name}: no store (offloading off for this member)")
        return
    shared = (
        "the team's store"
        if store is team.result_store
        else "its own settings, bound to the team db"
    )
    print(
        f"   {member.name}: {shared}; threshold={store.threshold_chars}, preview_lines={store.preview_lines}"
    )


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    session_id = "member-store-settings"
    team.print_response(
        "Ask the Inheriting Member about the api service, the Opted Out Member about "
        "the worker service, and the Own Settings Member about the scheduler service. "
        "Then give me the three error counts.",
        session_id=session_id,
    )

    print("\nEach member's store after the run:")
    for member in (inheriting, opted_out, own_settings):
        describe_member(member)

    print("\nWhat each member's stored history holds for its tool result:")
    session = db.get_session(session_id=session_id, session_type=SessionType.TEAM)
    for run in session.runs or []:
        member_id = getattr(run, "agent_id", None)
        if member_id is None:
            continue
        for message in run.messages or []:
            if message.role == "tool" and message.tool_name == "read_metrics":
                content = str(message.content or "")
                kind = "envelope" if content.startswith("<result id=") else "full text"
                print(f"   {member_id}: {kind}, {len(content)} characters")
                if kind == "envelope":
                    print("      " + content.split("\n")[0])
