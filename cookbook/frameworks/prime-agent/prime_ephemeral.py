"""Exercise fresh native runs with Agno's persisted-history fallback.

Each invocation uses --no-session, while Agno still saves runs in SQLite and
replays their history on the next turn. This is Agno history continuity.
"""

import tempfile
from os import getenv
from pathlib import Path
from uuid import uuid4

from agno.agents.prime import PrimeAgent
from agno.db.sqlite import SqliteDb


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agno-prime-ephemeral-") as state_dir:
        agent = PrimeAgent(
            id="prime-ephemeral",
            cwd=getenv("PRIME_AGENT_CWD", "."),
            db=SqliteDb(db_file=str(Path(state_dir) / "runs.db")),
            ephemeral=True,
            timeout=120,
        )
        session_id = str(uuid4())
        codename = "cedar-" + uuid4().hex[:8]
        agent.print_response(
            f"Remember the project codename is {codename}. Reply with OK.",
            session_id=session_id,
        )
        run = agent.print_response(
            "What is the project codename?", session_id=session_id
        )
        assert codename in str(run.content), run.content
        session = agent.get_session(session_id)
        assert session is not None and len(session.runs or []) == 2
        assert "prime_agent_session_id" not in (session.session_data or {})
        print(
            "PASS: saved two Agno runs and recalled history without a native session ID"
        )


if __name__ == "__main__":
    main()
