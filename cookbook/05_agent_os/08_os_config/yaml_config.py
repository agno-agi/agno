"""
Configure AgentOS with YAML
===========================

Load the same UI metadata and database-domain concepts as config_basics.py
from config.yaml, then verify the rendered result through GET /config.

Prerequisites: OPENAI_API_KEY is needed only for agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/08_os_config/yaml_config.py
Try: Run this file with --demo in another terminal
"""

import argparse
import os
from pathlib import Path

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create YAML-Configured AgentOS
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://localhost:7777")
AGENT_ID = "yaml-operations-agent"
DB_ID = "yaml-os-config-db"
CONFIG_PATH = Path(__file__).with_name("config.yaml")

db = SqliteDb(
    id=DB_ID,
    db_file="tmp/yaml_os_config.db",
)

operations_agent = Agent(
    id=AGENT_ID,
    name="YAML Operations Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Answer operations questions clearly and concisely.",
    add_history_to_context=True,
    num_history_runs=3,
    update_memory_on_run=True,
    markdown=True,
)

agent_os = AgentOS(
    id="yaml-config-os",
    description="AgentOS configured from YAML.",
    db=db,
    agents=[operations_agent],
    config=str(CONFIG_PATH),
)
app = agent_os.get_app()


def show_rendered_config() -> None:
    """Fetch and verify the YAML configuration rendered by AgentOS."""
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
        raise RuntimeError("GET /config did not preserve YAML available_models")
    if AGENT_ID not in {agent["id"] for agent in rendered["agents"]}:
        raise RuntimeError("The YAML manifest ID does not match a registered agent")
    if session_domain["db_id"] != DB_ID or memory_domain["db_id"] != DB_ID:
        raise RuntimeError("YAML db_ids do not match the registered database")
    if rendered["interfaces"]:
        raise RuntimeError("The YAML example unexpectedly registered an interface")

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
    print(f"Interfaces: {rendered['interfaces']}")


# ---------------------------------------------------------------------------
# Run YAML Config Demo
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
