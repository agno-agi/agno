"""Resume a Claude transcript from an Agno database in a fresh process.

Run with --verify to launch both processes; authentication must already be configured.
"""

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.db.sqlite import SqliteDb
from agno.run.base import RunStatus


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--turn", choices=["remember", "recall"])
    parser.add_argument("--db", default="tmp/claude-transcripts.db")
    parser.add_argument("--session", default="transcript-demo")
    args = parser.parse_args()
    if args.verify:
        with tempfile.TemporaryDirectory(prefix="agno-transcripts-") as temp:
            db = str(Path(temp) / "sessions.db")
            for turn in ("remember", "recall"):
                config = Path(temp) / turn
                config.mkdir()
                env = {**os.environ, "CLAUDE_CONFIG_DIR": str(config)}
                env.pop("AGNO_DEBUG", None)
                env.pop("AGNO_MONITOR", None)
                subprocess.run(
                    [sys.executable, __file__, "--turn", turn, "--db", db],
                    env=env,
                    check=True,
                )
        return
    if not args.turn:
        parser.error("Use --verify or --turn")
    agent = ClaudeAgent(
        id="transcript-demo",
        db=SqliteDb(db_file=args.db),
        allowed_tools=[],
        max_turns=2,
        max_budget_usd=0.5,
    )
    prompt = (
        "Remember this exact secret phrase: cobalt orchard 742. Reply OK."
        if args.turn == "remember"
        else "What exact secret phrase did I tell you? Reply only with that phrase."
    )
    result = agent.run(prompt, session_id=args.session)
    assert result.status == RunStatus.completed, result.content
    print(result.content)
    if args.turn == "remember":
        session = agent.get_run_output(result.run_id, args.session)
        assert session is not None
        stored = agent.db.list_transcript_sessions(agent.framework, agent.get_id())
        assert stored, "The SDK did not mirror a transcript"
        # Remove Agno conversation history so the second process must use the SDK transcript.
        agent.db.delete_run(result.run_id)
    else:
        assert "cobalt orchard 742" in result.content.lower(), result.content
        print("PASS: recalled the stored transcript from a fresh process and empty config directory")


if __name__ == "__main__":
    main()
