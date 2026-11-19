"""Recreate the adapter and resume the native ID stored in Agno's database.

Both adapters use the same ID, user, database and native session directory.
This checks adapter recreation on one host; it does not simulate a CLI crash.
"""

import tempfile
from os import getenv
from pathlib import Path
from uuid import uuid4

from agno.agents.prime import PrimeAgent
from agno.db.sqlite import SqliteDb


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agno-prime-recovery-") as state_dir:
        db = SqliteDb(db_file=str(Path(state_dir) / "runs.db"))
        native_dir = str(Path(state_dir) / "native")
        cwd = getenv("PRIME_AGENT_CWD", ".")
        session_id = str(uuid4())
        user_id = "prime-recovery-user"
        codename = "maple-" + uuid4().hex[:8]
        original = PrimeAgent(
            id="prime-recovery", cwd=cwd, db=db, session_dir=native_dir, timeout=120
        )
        original.print_response(
            f"Remember the project codename is {codename}. Reply with OK.",
            session_id=session_id,
            user_id=user_id,
        )
        session = original.get_session(session_id, user_id)
        assert session is not None
        native_id = (session.session_data or {}).get("prime_agent_session_id")
        assert native_id, "Prime did not emit a native session ID"

        restored = PrimeAgent(
            id="prime-recovery", cwd=cwd, db=db, session_dir=native_dir, timeout=120
        )
        run = restored.print_response(
            "What is the project codename?",
            session_id=session_id,
            user_id=user_id,
        )
        assert codename in str(run.content), run.content
        session = restored.get_session(session_id, user_id)
        assert session is not None and len(session.runs or []) == 2
        assert (session.session_data or {}).get("prime_agent_session_id") == native_id
        print(f"PASS: adapter recreation retained native session {native_id}")


if __name__ == "__main__":
    main()
