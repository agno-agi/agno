"""Share one ClaudeAgent session between users.

A session belongs to the user who started it. The owner (or an admin) shares it with named
members; members then continue the same Claude conversation, and every run keeps its own
user_id. Anyone else is refused. Over AgentOS, the owner calls PUT /sessions/{id}/sharing.
"""

import tempfile
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.session.sharing import share_session

with tempfile.TemporaryDirectory(prefix="agno-shared-") as workdir:
    db = SqliteDb(db_file=str(Path(workdir) / "sessions.db"))
    agent = ClaudeAgent(
        id="shared-demo",
        model="claude-sonnet-4-6",
        db=db,
        cwd=workdir,
        allowed_tools=[],
        max_turns=2,
        max_budget_usd=0.5,
    )

    alice = agent.run(
        "Remember the codeword PELICAN. Reply OK.", session_id="team", user_id="alice"
    )
    print(f"alice: {alice.content}")

    share_session(db, "team", ["bob"], user_id="alice")

    bob = agent.run(
        "What codeword were you asked to remember? Reply with the word only.",
        session_id="team",
        user_id="bob",
    )
    print(f"bob: {bob.content}")
    assert "PELICAN" in (bob.content or "").upper(), bob.content

    try:
        agent.run("What is the codeword?", session_id="team", user_id="carol")
    except ValueError as error:
        print(f"carol: refused ({error})")

    session = agent.get_session("team")
    print(
        "Runs:",
        [
            (run.user_id, run.input.input_content if run.input else None)
            for run in session.runs or []
        ],
    )
