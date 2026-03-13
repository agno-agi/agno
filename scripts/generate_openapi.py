"""Generate the OpenAPI schema for AgentOS without starting a server.

Creates a maximal AgentOS instance with all routes registered,
extracts the OpenAPI JSON via FastAPI's app.openapi(), and writes
it to stdout (or a file path passed as the first argument).

Usage:
    python scripts/generate_openapi.py                     # writes to stdout
    python scripts/generate_openapi.py openapi.json        # writes to file
"""

import json
import os
import sys

# Slack interface requires SLACK_TOKEN at init time (creates WebClient).
# Set a dummy value so the interface can register its routes.
os.environ.setdefault("SLACK_TOKEN", "schema-generation-placeholder")

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.os.app import AgentOS
from agno.os.interfaces.a2a import A2A
from agno.os.interfaces.agui import AGUI
from agno.os.interfaces.slack import Slack
from agno.os.interfaces.whatsapp import Whatsapp
from agno.registry import Registry
from agno.team import Team
from agno.workflow import Workflow


def generate_openapi_schema() -> dict:
    """Build a maximal AgentOS and return the OpenAPI schema dict."""
    db = InMemoryDb()
    registry = Registry()

    agent = Agent(name="agent", db=db)
    team = Team(members=[agent], name="team", db=db)
    workflow = Workflow(name="workflow")

    interfaces = [
        A2A(agents=[agent], teams=[team], workflows=[workflow]),
        AGUI(agent=agent),
        Slack(agent=agent),
        Whatsapp(agent=agent),
    ]

    agent_os = AgentOS(
        name="agno-api-reference",
        db=db,
        agents=[agent],
        teams=[team],
        workflows=[workflow],
        interfaces=interfaces,
        registry=registry,
        auto_provision_dbs=False,
        telemetry=False,
    )

    app = agent_os.get_app()
    return app.openapi()


def main() -> None:
    schema = generate_openapi_schema()
    output = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"

    if len(sys.argv) > 1:
        outpath = sys.argv[1]
        with open(outpath, "w") as f:
            f.write(output)
        print(f"Wrote OpenAPI schema to {outpath}", file=sys.stderr)
    else:
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
