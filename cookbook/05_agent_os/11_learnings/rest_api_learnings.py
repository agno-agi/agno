"""
Read Agent Learning over REST
=============================

Run a learning-enabled agent, read its extracted profile and memory through
the REST API, then exercise create, list, get, patch, and delete operations.

Prerequisites: learnings_with_agentos.py running on http://localhost:7777
Run: .venvs/demo/bin/python cookbook/05_agent_os/11_learnings/rest_api_learnings.py
Try: Compare the agent-written records with the manually created record
"""

import os
from typing import Any
from uuid import uuid4

import httpx

# ---------------------------------------------------------------------------
# Create Learnings API Helpers
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://localhost:7777")
AGENT_ID = "learning-assistant"


def delete_user(client: httpx.Client, user_id: str) -> None:
    """Remove every learning owned by one demo user."""
    response = client.delete(f"/learnings/users/{user_id}")
    if response.status_code != 204:
        response.raise_for_status()
        raise RuntimeError("Learning-user cleanup did not return 204")


def list_user_learnings(client: httpx.Client, user_id: str) -> dict[str, Any]:
    """List every learning currently owned by one user."""
    response = client.get(
        "/learnings",
        params={"user_id": user_id, "limit": 20, "page": 1},
    )
    response.raise_for_status()
    return response.json()


def verify_server(client: httpx.Client) -> None:
    """Verify health and discovery for the learning-enabled agent."""
    health_response = client.get("/health")
    health_response.raise_for_status()

    config_response = client.get("/config")
    config_response.raise_for_status()
    config = config_response.json()
    agent_ids = {agent["id"] for agent in config["agents"]}
    if AGENT_ID not in agent_ids:
        raise RuntimeError(f"Agent {AGENT_ID} was not discovered")

    print(f"Health: {health_response.json()['status']}")
    print(f"Agent: {AGENT_ID}")


def run_agent_learning(
    client: httpx.Client,
    user_id: str,
    session_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the agent and read the profile and memory written by that run."""
    response = client.post(
        f"/agents/{AGENT_ID}/runs",
        data={
            "message": (
                "My name is Mira Chen. I design distributed systems and "
                "prefer concise numbered answers. Please remember that."
            ),
            "stream": "false",
            "user_id": user_id,
            "session_id": session_id,
        },
    )
    response.raise_for_status()
    run = response.json()
    if run["status"] != "COMPLETED":
        raise RuntimeError(f"Agent run ended with {run['status']}")

    records = list_user_learnings(client, user_id)
    records_by_type = {
        item["learning_type"]: item
        for item in records["data"]
        if item["learning_type"] in {"user_profile", "user_memory"}
    }
    learning_types = set(records_by_type)
    expected_types = {"user_profile", "user_memory"}
    if not expected_types.issubset(learning_types):
        raise RuntimeError(
            f"Agent learning was incomplete: found {sorted(learning_types)}"
        )

    profile = records_by_type["user_profile"]["content"]
    memory = records_by_type["user_memory"]["content"]
    if "Mira" not in str(profile):
        raise RuntimeError("Agent-written profile did not retain the user's name")
    if "concise" not in str(memory).lower():
        raise RuntimeError(
            "Agent-written memory did not retain the response preference"
        )

    print(f"Agent run status: {run['status']}")
    print(f"Agent-written profile: {profile}")
    print(f"Agent-written memory: {memory}")
    return run, records


def run_manual_crud(client: httpx.Client, user_id: str) -> dict[str, Any]:
    """Exercise the manual learning CRUD and bulk-delete routes."""
    create_response = client.post(
        "/learnings",
        json={
            "learning_type": "user_profile",
            "namespace": "global",
            "user_id": user_id,
            "content": {
                "user_id": user_id,
                "name": "Yash",
                "preferences": {"language": "Python", "tone": "concise"},
            },
            "metadata": {"source": "11_learnings"},
        },
    )
    if create_response.status_code != 201:
        create_response.raise_for_status()
        raise RuntimeError("Learning creation did not return 201")
    created = create_response.json()
    learning_id = created["learning_id"]

    listed = list_user_learnings(client, user_id)
    if learning_id not in {item["learning_id"] for item in listed["data"]}:
        raise RuntimeError("Created learning was missing from the list")

    users_response = client.get(
        "/learnings/users",
        params={"user_id": user_id},
    )
    users_response.raise_for_status()
    users = users_response.json()
    if not users["data"] or users["data"][0]["user_id"] != user_id:
        raise RuntimeError("Learning user was missing from the users index")

    get_response = client.get(f"/learnings/{learning_id}")
    get_response.raise_for_status()
    fetched = get_response.json()
    if fetched["learning_id"] != learning_id:
        raise RuntimeError("GET returned the wrong learning")
    if fetched["content"]["user_id"] != user_id:
        raise RuntimeError("GET did not preserve the profile identity")

    patch_response = client.patch(
        f"/learnings/{learning_id}",
        json={
            "content": {
                "user_id": user_id,
                "name": "Yash",
                "preferences": {
                    "language": "Python",
                    "tone": "concise",
                    "focus": "agent infrastructure",
                },
            },
            "metadata": {"source": "11_learnings", "version": 2},
        },
    )
    patch_response.raise_for_status()
    updated = patch_response.json()
    if updated["metadata"] != {"source": "11_learnings", "version": 2}:
        raise RuntimeError("PATCH did not replace the learning metadata")
    if updated["content"]["preferences"]["focus"] != "agent infrastructure":
        raise RuntimeError("PATCH did not replace the learning content")

    delete_response = client.delete(f"/learnings/{learning_id}")
    if delete_response.status_code != 204:
        delete_response.raise_for_status()
        raise RuntimeError("Learning deletion did not return 204")

    missing_response = client.get(f"/learnings/{learning_id}")
    if missing_response.status_code != 404:
        raise RuntimeError("Deleted learning was still retrievable")

    for note in ("first", "second"):
        seed_response = client.post(
            "/learnings",
            json={
                "learning_type": "decision_log",
                "user_id": user_id,
                "content": {"note": note},
                "metadata": {"source": "11_learnings"},
            },
        )
        if seed_response.status_code != 201:
            seed_response.raise_for_status()
            raise RuntimeError("Decision-log creation did not return 201")

    delete_user(client, user_id)
    remaining = list_user_learnings(client, user_id)
    if remaining["meta"]["total_count"] != 0:
        raise RuntimeError("Bulk user deletion left learning records behind")

    print(f"Created learning: {learning_id}")
    print(f"List total: {listed['meta']['total_count']}")
    print(f"Learning user last updated: {users['data'][0]['last_learning_updated_at']}")
    print(f"Fetched content: {fetched['content']}")
    print(f"Updated content: {updated['content']}")
    print(f"Updated metadata: {updated['metadata']}")
    print(f"Delete status: {delete_response.status_code}")
    print(f"Follow-up GET status: {missing_response.status_code}")
    print(f"Remaining after user delete: {remaining['meta']['total_count']}")
    return updated


# ---------------------------------------------------------------------------
# Run Agent and Learnings REST Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_suffix = uuid4().hex[:8]
    agent_user_id = f"agent-learning-{run_suffix}"
    crud_user_id = f"crud-learning-{run_suffix}"
    session_id = f"learning-session-{run_suffix}"

    with httpx.Client(base_url=BASE_URL, timeout=300.0) as http_client:
        verify_server(http_client)
        delete_user(http_client, agent_user_id)
        delete_user(http_client, crud_user_id)

        try:
            run_agent_learning(http_client, agent_user_id, session_id)
            run_manual_crud(http_client, crud_user_id)
        finally:
            delete_user(http_client, agent_user_id)
            delete_user(http_client, crud_user_id)
