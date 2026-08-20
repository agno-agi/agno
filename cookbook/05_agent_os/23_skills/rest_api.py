"""
Manage Skills over REST
=======================

Serve an AgentOS backed by a database and drive the five /skills endpoints
with raw HTTP: create, list, read, update with the version guard, and delete.

Prerequisites: none (the agent's model is never invoked)
Run: .venvs/demo/bin/python cookbook/05_agent_os/23_skills/rest_api.py
Try: In another terminal, rerun this file with --demo
"""

import argparse
import os

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.skills import DbSkills, Skills

# ---------------------------------------------------------------------------
# Create Skills API AgentOS
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://127.0.0.1:7777")
PORT = int(os.getenv("AGENT_OS_PORT", "7777"))
AGENT_ID = "skills-api-agent"
SKILL_NAME = "release-notes"

db = SqliteDb(db_file="tmp/skills_rest_api.db")

# The served agent resolves its skills from the same table the API manages,
# so a skill created over HTTP is available on the agent's next request.
api_agent = Agent(
    id=AGENT_ID,
    name="Skills API Agent",
    model=OpenAIResponses(id="gpt-5.6"),
    db=db,
    skills=Skills(loaders=[DbSkills(db)]),
    instructions=[
        "Use the release-notes skill when asked to draft release notes.",
    ],
)

agent_os = AgentOS(
    id="skills-api-agent-os",
    description="AgentOS serving the skills management REST API.",
    agents=[api_agent],
)
app = agent_os.get_app()

SKILL_BODY = {
    "name": SKILL_NAME,
    "description": "Draft release notes in the house style.",
    "instructions": (
        "Read style.md with get_skill_reference, then draft release notes "
        "that follow it: one line per change, present tense, no adjectives."
    ),
    "references": {
        "style.md": "One line per change. Present tense. No adjectives.\n",
    },
}


def delete_existing(client: httpx.Client) -> None:
    """Remove an earlier copy so the walkthrough is repeatable."""
    response = client.delete(f"/skills/{SKILL_NAME}")
    if response.status_code not in {204, 404}:
        response.raise_for_status()


def run_demo() -> None:
    """Exercise the complete skills REST lifecycle."""
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        health_response = client.get("/health")
        health_response.raise_for_status()

        config_response = client.get("/config")
        config_response.raise_for_status()
        config = config_response.json()
        agent_ids = {agent["id"] for agent in config["agents"]}
        if config["os_id"] != agent_os.id or AGENT_ID not in agent_ids:
            raise RuntimeError("AgentOS did not discover the skills API Agent")
        print(f"Health: {health_response.json()['status']}")
        print(f"AgentOS: {config['os_id']}")

        delete_existing(client)

        create_response = client.post("/skills", json=SKILL_BODY)
        if create_response.status_code != 201:
            raise RuntimeError(
                f"Expected 201 from POST, got {create_response.status_code}"
            )
        created = create_response.json()
        if (
            created["version"] != 1
            or created["instructions"] != SKILL_BODY["instructions"]
        ):
            raise RuntimeError(
                "Created skill did not return version 1 with full content"
            )
        print(f"POST /skills -> 201 ({created['name']}, version {created['version']})")

        duplicate_response = client.post("/skills", json=SKILL_BODY)
        if duplicate_response.status_code != 409:
            raise RuntimeError(
                f"Expected 409 for a duplicate name, got {duplicate_response.status_code}"
            )
        print("Duplicate POST /skills -> 409")

        list_response = client.get("/skills", params={"limit": 100, "page": 1})
        list_response.raise_for_status()
        listed = list_response.json()
        summary = next(
            (row for row in listed["data"] if row["name"] == SKILL_NAME), None
        )
        if summary is None:
            raise RuntimeError("Created skill missing from the list")
        if "instructions" in summary or "references" in summary:
            raise RuntimeError("List endpoint returned content fields")
        print(f"GET /skills -> listed {SKILL_NAME}, metadata only")

        detail_response = client.get(f"/skills/{SKILL_NAME}")
        detail_response.raise_for_status()
        detail = detail_response.json()
        if detail["references"] != SKILL_BODY["references"]:
            raise RuntimeError("Detail endpoint did not return the stored content")
        print(f"GET /skills/{SKILL_NAME} -> full content")

        patch_response = client.patch(
            f"/skills/{SKILL_NAME}",
            json={
                "version": 1,
                "description": "Draft release notes in the new house style.",
            },
        )
        patch_response.raise_for_status()
        updated = patch_response.json()
        if updated["version"] != 2:
            raise RuntimeError(
                f"Expected version 2 after PATCH, got {updated['version']}"
            )
        print("PATCH /skills -> version 1 -> 2")

        stale_response = client.patch(
            f"/skills/{SKILL_NAME}",
            json={"version": 1, "description": "An edit against a version that moved."},
        )
        if stale_response.status_code != 409:
            raise RuntimeError(
                f"Expected 409 for a stale version, got {stale_response.status_code}"
            )
        if "current version is 2" not in stale_response.json()["detail"]:
            raise RuntimeError("Version conflict did not name the current version")
        print("Stale PATCH (version 1 again) -> 409 naming current version 2")

        delete_response = client.delete(f"/skills/{SKILL_NAME}")
        if delete_response.status_code != 204:
            raise RuntimeError(
                f"Expected 204 from DELETE, got {delete_response.status_code}"
            )
        print(f"DELETE /skills/{SKILL_NAME} -> 204")

        missing_response = client.get(f"/skills/{SKILL_NAME}")
        if missing_response.status_code != 404:
            raise RuntimeError(
                f"Expected 404 after delete, got {missing_response.status_code}"
            )
        print("GET after delete -> 404")


# ---------------------------------------------------------------------------
# Run Skills API AgentOS or Demo
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
