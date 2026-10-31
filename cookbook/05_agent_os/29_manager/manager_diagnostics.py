"""Run diagnostics for an AgentOS with an OS manager. No model calls.

Prints the report that Platform Manager reads through its run_diagnostics
tool. A missing OPENAI_API_KEY is reported as a failure, but does not stop
the checks from running.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/29_manager/manager_diagnostics.py
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, OSManager


def main() -> None:
    with TemporaryDirectory() as directory:
        db = SqliteDb(db_file=str(Path(directory) / "os.db"))
        agent_os = AgentOS(
            db=db,
            manager=OSManager(
                required_env=("OPENAI_API_KEY",),
                model=OpenAIResponses(id="gpt-5.6-luna"),
            ),
            telemetry=False,
        )

        report = agent_os.run_diagnostics()
        print("Diagnostics:", report.status)
        print(json.dumps(report.to_dict(), indent=2))


if __name__ == "__main__":
    main()
