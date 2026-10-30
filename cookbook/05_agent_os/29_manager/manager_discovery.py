"""List agents with manifest descriptions through OS Manager. No model calls.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/29_manager/manager_discovery.py
"""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, OSManager
from agno.os.config import AgentOSConfig, Manifest
from agno.tools.studio_runner import StudioRunnerTools


def main() -> None:
    model = OpenAIResponses(id="gpt-5.6-luna")
    daily_brief = Agent(id="daily-brief", name="Daily Brief", model=model)
    description = "Summarize the day's agent framework and model releases."
    with TemporaryDirectory() as directory:
        agent_os = AgentOS(
            db=SqliteDb(db_file=str(Path(directory) / "os.db")),
            agents=[daily_brief],
            manager=OSManager(model=model, access_docs=False),
            config=AgentOSConfig(
                manifest={"daily-brief": Manifest(description=description)}
            ),
            telemetry=False,
        )
        assert agent_os.manager is not None
        runner = next(
            tool
            for tool in agent_os.manager.tools
            if isinstance(tool, StudioRunnerTools)
        )
        listing = json.loads(runner.list_agents())
        assert listing == json.loads(asyncio.run(runner.alist_agents()))
        assert listing["agents"][0]["description"] == description
        assert daily_brief.description is None
        print(json.dumps(listing, indent=2))


if __name__ == "__main__":
    main()
