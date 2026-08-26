"""
Watch to Team
=============

Deliver a change to a team instead of one agent. Three reviewers with three
concerns; the leader picks which ones the change needs and merges their answers.

Prerequisites: OPENAI_API_KEY and pip install agno watchfiles
Run: .venvs/demo/bin/python cookbook/05_agent_os/26_monitor/02_watch_to_team.py
Try: Run this file with --demo in another terminal
"""

import sys
import time
from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.monitor import MonitorConfig, MonitorManager
from agno.os import AgentOS
from agno.team import Team
from agno.tools.file import FileTools

# The workspace the watch covers and the reviewers may read.
WATCH_ROOT = Path("tmp/team_watch")

# Both trees, watched together as one monitor. Given relative to WATCH_ROOT,
# which is the root AgentOS contains every watch_path inside.
WATCHED_PATHS = ["src", "tests"]

TEAM_ID = "review-team"

# One session for every review, so the tenth change is reviewed with the
# previous nine in view rather than cold.
REVIEW_SESSION = "team-review-session"

db = SqliteDb(id="watch-to-team", db_file="tmp/watch_to_team.db")

READ_THE_CHANGE = [
    "Each message lists the files that changed, one per line, as an action and an absolute path.",
    "Read a changed file with read_file, passing the path relative to the watched root",
    "-- 'src/auth.py', not the absolute path.",
]

security_reviewer = Agent(
    id="security-reviewer",
    name="Security Reviewer",
    role="You review changes for security problems only.",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[FileTools(base_dir=WATCH_ROOT)],
    instructions=[
        *READ_THE_CHANGE,
        "Look for injection, unvalidated input, secrets and weak auth.",
        "Say nothing about style or performance.",
    ],
)

performance_reviewer = Agent(
    id="performance-reviewer",
    name="Performance Reviewer",
    role="You review changes for performance problems only.",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[FileTools(base_dir=WATCH_ROOT)],
    instructions=[
        *READ_THE_CHANGE,
        "Look for work inside loops, repeated I/O and N+1 queries.",
        "Say nothing about security or docs.",
    ],
)

docs_reviewer = Agent(
    id="docs-reviewer",
    name="Docs Reviewer",
    role="You review changes for documentation and naming only.",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[FileTools(base_dir=WATCH_ROOT)],
    instructions=[
        *READ_THE_CHANGE,
        "Check that names say what things are and non-obvious code is commented.",
        "Say nothing about security or performance.",
    ],
)

review_team = Team(
    id=TEAM_ID,
    name="Review Team",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[security_reviewer, performance_reviewer, docs_reviewer],
    # The leader needs FileTools too. The event names a file, it never carries
    # the code -- so a leader that answers without delegating has nothing to
    # review and says so instead of reviewing.
    tools=[FileTools(base_dir=WATCH_ROOT)],
    db=db,
    instructions=[
        "You review code changes the moment they are saved.",
        "The message names changed files, it does NOT contain the code.",
        "Always read each named file with read_file before saying anything about it.",
        "Send the change to the members whose concern it touches; a test file rarely needs all three.",
        "Merge what they report into one short verdict, keeping each member's concern separate.",
        "Lead with anything that must be fixed before this is committed.",
    ],
)


agent_os = AgentOS(
    name="Team Review OS",
    teams=[review_team],
    db=db,
    monitors=MonitorConfig(
        base_dir=str(WATCH_ROOT),
        poll_interval=2,  # seconds between poll cycles (default: 5)
    ),
)
app = agent_os.get_app()


def ensure_workspace() -> None:
    """Create both watched trees.

    A path watch refuses to start on a path that is not there, naming the
    missing one -- so the directories have to exist before the poller claims the
    monitor, not by the time somebody edits a file in them.
    """
    for path in WATCHED_PATHS:
        (WATCH_ROOT / path).mkdir(parents=True, exist_ok=True)


def ensure_monitor() -> None:
    """Create the file watch once, so a server restart reuses the same row."""
    # The manager resolves watch_path against the same root AgentOS was given.
    manager = MonitorManager(db=db, base_dir=str(WATCH_ROOT))
    existing = manager.list(status=None)
    if existing:
        print(f"Reusing monitor {existing[0].id} ({existing[0].status})")
        return

    monitor = manager.create(
        name="team-review-on-save",
        # Two directories, one watcher, one row. The list form is what keeps the
        # row's single status and single event count honest across both trees.
        watch_path=WATCHED_PATHS,
        description="Review every change under src/ and tests/",
        # The only line that differs from delivering to one agent.
        endpoint=f"/teams/{TEAM_ID}/runs",
        payload={
            "message": "These files just changed. Review the change.",
            "session_id": REVIEW_SESSION,
        },
        persistent=True,  # watch until stopped, with no timeout
        # Every delivered event starts a real team run, and a team run is
        # several model calls, not one. Cap it.
        max_events=20,
    )
    watched = ", ".join(WATCHED_PATHS)
    print(f"Watching {watched} under {WATCH_ROOT} as monitor {monitor.id}")


def run_demo() -> None:
    """Save a file with a real security bug in it, then print what the team said."""
    import httpx

    with httpx.Client(base_url="http://127.0.0.1:7777", timeout=30) as client:
        # Say what to do, rather than let httpx raise a bare Connection refused.
        try:
            client.get("/health")
        except httpx.ConnectError:
            print("No AgentOS on http://127.0.0.1:7777.")
            print("Start it first, in another terminal:")
            print("    python cookbook/05_agent_os/26_monitor/02_watch_to_team.py")
            return

        # Count what is already there BEFORE saving, or the new event is counted
        # in the baseline and this waits for a second one that never comes.
        monitor_id = client.get("/monitors").json()["data"][0]["id"]
        seen = client.get(f"/monitors/{monitor_id}/events").json()["meta"][
            "total_count"
        ]

        target = WATCH_ROOT / "src" / "auth.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"Saving {target} with a SQL injection in it...")
        target.write_text(
            "def login(u, p): return db.query('select * from x where n=' + u)\n"
        )

        print("Waiting for the team to review it...")
        run_id = None
        for _ in range(60):
            time.sleep(2)
            events = client.get(f"/monitors/{monitor_id}/events").json()["data"]
            if len(events) > seen and events[0]["run_id"]:
                print(f"Event: {events[0]['content']}")
                run_id = events[0]["run_id"]
                break
        if run_id is None:
            raise TimeoutError("No event was delivered; is the server running?")

        for _ in range(60):
            run = client.get(
                f"/teams/{TEAM_ID}/runs/{run_id}", params={"session_id": REVIEW_SESSION}
            ).json()
            if run.get("content"):
                print("\nWhat the team said:\n")
                print(run["content"])
                return
            time.sleep(2)
    raise TimeoutError("The team run did not finish in time")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_demo()
    else:
        ensure_workspace()
        ensure_monitor()
        agent_os.serve(app=app)
