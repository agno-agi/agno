"""
Serve an Agent with a Local Skill
=================================

Load a skill from disk, expose its instructions and scripts to an Agent, and
prove a real script execution through the AgentOS run API.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/23_skills/basic.py
Try: In another terminal, rerun this file with --demo
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.skills import LocalSkills, Skills

# ---------------------------------------------------------------------------
# Create Skills AgentOS
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://127.0.0.1:7777")
PORT = int(os.getenv("AGENT_OS_PORT", "7777"))
AGENT_ID = "skills-agent"
SESSION_ID = "skills-live-demo"
SKILLS_DIR = Path(__file__).parent / "sample_skills"

skills_agent = Agent(
    id=AGENT_ID,
    name="Skills Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    skills=Skills(loaders=[LocalSkills(str(SKILLS_DIR))]),
    instructions=[
        "For a system information request, first call get_skill_instructions "
        "with skill_name='system-info'.",
        "Then call get_skill_script with skill_name='system-info', "
        "script_path='get_system_info.py', and execute=true.",
        "Read the JSON in the script stdout. If returncode is not zero, report "
        "the failure instead of inventing an answer.",
        "Report the hostname, operating system, and Python version only from "
        "the executed script's stdout.",
    ],
)

agent_os = AgentOS(
    id="skills-agent-os",
    description="AgentOS serving an Agent with executable local skills.",
    agents=[skills_agent],
)
app = agent_os.get_app()


def require_tool(run: dict[str, Any], tool_name: str) -> dict[str, Any]:
    """Return one recorded tool execution or fail the live proof."""
    tool = next(
        (item for item in run.get("tools") or [] if item["tool_name"] == tool_name),
        None,
    )
    if tool is None:
        raise RuntimeError(f"The run did not record {tool_name}")
    if tool.get("tool_call_error"):
        raise RuntimeError(f"{tool_name} failed: {tool.get('result')}")
    return tool


def run_demo() -> None:
    """Execute the local skill through a model-backed AgentOS run."""
    with httpx.Client(base_url=BASE_URL, timeout=180.0) as client:
        health_response = client.get("/health")
        health_response.raise_for_status()

        config_response = client.get("/config")
        config_response.raise_for_status()
        config = config_response.json()
        agent_ids = {agent["id"] for agent in config["agents"]}
        if config["os_id"] != agent_os.id or AGENT_ID not in agent_ids:
            raise RuntimeError("AgentOS did not discover the skills Agent")

        run_response = client.post(
            f"/agents/{AGENT_ID}/runs",
            data={
                "message": (
                    "Use the system-info skill. Load its instructions, then "
                    "execute get_system_info.py. Report the hostname, operating "
                    "system, and Python version from its actual stdout."
                ),
                "session_id": SESSION_ID,
                "stream": "false",
            },
        )
        run_response.raise_for_status()
        run = run_response.json()

    if run["status"] != "COMPLETED":
        raise RuntimeError(f"Expected COMPLETED, got {run['status']}")

    require_tool(run, "get_skill_instructions")
    script_tool = require_tool(run, "get_skill_script")
    script_args = script_tool.get("tool_args") or {}
    if script_args.get("execute") is not True:
        raise RuntimeError("The model did not request executable script mode")

    script_result = json.loads(script_tool["result"])
    if script_result["returncode"] != 0:
        raise RuntimeError(f"Skill script failed: {script_result['stderr']}")
    system_info = json.loads(script_result["stdout"])
    required_fields = {"hostname", "os", "python_version"}
    if not required_fields.issubset(system_info):
        raise RuntimeError("Skill stdout omitted required system information")

    print(f"Health: {health_response.json()['status']}")
    print(f"AgentOS: {config['os_id']}")
    print(f"Agent: {AGENT_ID}")
    print("Tools: get_skill_instructions -> get_skill_script (execute=True)")
    print(
        "Script result: "
        f"returncode={script_result['returncode']}, "
        f"hostname={system_info['hostname']}, "
        f"os={system_info['os']}, "
        f"python={system_info['python_version']}"
    )
    print(f"Run: {run['run_id']} -> {run['status']}")
    print(f"Response: {run['content']}")


# ---------------------------------------------------------------------------
# Run Skills AgentOS or Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the HTTP client against the configured AgentOS URL.",
    )
    args = parser.parse_args()

    if args.demo:
        run_demo()
    else:
        agent_os.serve(app=app, host="127.0.0.1", port=PORT)
