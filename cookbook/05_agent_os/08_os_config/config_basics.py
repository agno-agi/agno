"""
Configure AgentOS in Python
===========================

Attach UI metadata and database-domain labels to an AgentOSConfig, then fetch
GET /config to inspect the rendered control-plane configuration.

Prerequisites: OPENAI_API_KEY is needed only for agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/08_os_config/config_basics.py
Try: Run this file with --demo in another terminal
"""

import argparse
import os

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import (
    AgentOSConfig,
    DatabaseConfig,
    Manifest,
    MemoryConfig,
    MemoryDomainConfig,
    SessionConfig,
    SessionDomainConfig,
)

# ---------------------------------------------------------------------------
# Create Configured AgentOS
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://localhost:7777")
AGENT_ID = "operations-agent"
DB_ID = "os-config-db"

db = SqliteDb(
    id=DB_ID,
    db_file="tmp/os_config.db",
)

operations_agent = Agent(
    id=AGENT_ID,
    name="Operations Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Answer operations questions clearly and concisely.",
    add_history_to_context=True,
    num_history_runs=3,
    update_memory_on_run=True,
    markdown=True,
)

os_config = AgentOSConfig(
    available_models=["gpt-5.5"],
    manifest={
        AGENT_ID: Manifest(
            description="Answers operational questions and summarizes next steps.",
            labels=["operations", "production"],
            quick_prompts=[
                "Summarize the current operational priorities.",
                "Turn these notes into an action plan.",
                "What should I investigate first?",
            ],
        )
    },
    session=SessionConfig(
        dbs=[
            DatabaseConfig(
                db_id=DB_ID,
                domain_config=SessionDomainConfig(
                    display_name="Operations conversations"
                ),
            )
        ]
    ),
    memory=MemoryConfig(
        dbs=[
            DatabaseConfig(
                db_id=DB_ID,
                domain_config=MemoryDomainConfig(display_name="Operations preferences"),
            )
        ]
    ),
)

agent_os = AgentOS(
    id="python-config-os",
    description="AgentOS configured with Python objects.",
    db=db,
    agents=[operations_agent],
    config=os_config,
)
app = agent_os.get_app()


def show_rendered_config() -> None:
    """Fetch and verify the configuration rendered by AgentOS."""
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        health_response = client.get("/health")
        health_response.raise_for_status()

        config_response = client.get("/config")
        config_response.raise_for_status()
        rendered = config_response.json()

    manifest = rendered["manifest"][AGENT_ID]
    session_domain = rendered["session"]["dbs"][0]
    memory_domain = rendered["memory"]["dbs"][0]

    if rendered["available_models"] != ["gpt-5.5"]:
        raise RuntimeError("GET /config did not preserve available_models")
    if AGENT_ID not in {agent["id"] for agent in rendered["agents"]}:
        raise RuntimeError("The manifest ID does not match a registered agent")
    if session_domain["db_id"] != DB_ID or memory_domain["db_id"] != DB_ID:
        raise RuntimeError("A configured domain points at an unknown database")

    print(f"Health: {health_response.json()['status']}")
    print(f"AgentOS: {rendered['os_id']}")
    print(f"Available models: {rendered['available_models']}")
    print(f"Manifest labels: {manifest['labels']}")
    print(f"Quick prompts: {manifest['quick_prompts']}")
    print(
        "Session domain: "
        f"{session_domain['domain_config']['display_name']} ({session_domain['db_id']})"
    )
    print(
        "Memory domain: "
        f"{memory_domain['domain_config']['display_name']} ({memory_domain['db_id']})"
    )


# ---------------------------------------------------------------------------
# Run Config Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Fetch GET /config from a server already running on port 7777.",
    )
    args = parser.parse_args()

    if args.demo:
        show_rendered_config()
    else:
        agent_os.serve(app=app)
