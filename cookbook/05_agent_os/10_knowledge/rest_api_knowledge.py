"""
Manage Knowledge over REST
==========================

Exercise the complete AgentOS knowledge-content lifecycle over raw HTTP:
upload, poll processing, list, semantic search, delete, and verify deletion.

Prerequisites: basic.py running on http://localhost:7777
Run: .venvs/demo/bin/python cookbook/05_agent_os/10_knowledge/rest_api_knowledge.py
Try: Watch the accepted upload reach completed before search begins
"""

import json
import os
import time
from typing import Any
from uuid import uuid4

import httpx

# ---------------------------------------------------------------------------
# Create Knowledge API Helpers
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("AGENT_OS_BASE_URL", "http://localhost:7777")
AGENT_ID = "knowledge-assistant"
KNOWLEDGE_NAME = "AgentOS Knowledge"


def wait_until_processed(client: httpx.Client, content_id: str) -> dict[str, Any]:
    """Poll one content item until processing reaches a terminal state."""
    for _ in range(60):
        response = client.get(f"/knowledge/content/{content_id}/status")
        response.raise_for_status()
        status = response.json()
        print(f"Content status: {status['status']}")

        if status["status"] == "completed":
            return status
        if status["status"] == "failed":
            raise RuntimeError(
                status.get("status_message") or "Knowledge processing failed"
            )
        time.sleep(0.5)

    raise TimeoutError("Knowledge content did not finish processing")


def verify_server(client: httpx.Client) -> None:
    """Verify health and the served agent and knowledge configuration."""
    health_response = client.get("/health")
    health_response.raise_for_status()
    if health_response.json()["status"] != "ok":
        raise RuntimeError("AgentOS health check did not return ok")

    config_response = client.get("/config")
    config_response.raise_for_status()
    config = config_response.json()

    agent_ids = {agent["id"] for agent in config["agents"]}
    knowledge_names = {
        instance["name"] for instance in config["knowledge"]["knowledge_instances"]
    }
    if AGENT_ID not in agent_ids:
        raise RuntimeError(f"Agent {AGENT_ID} was not discovered")
    if KNOWLEDGE_NAME not in knowledge_names:
        raise RuntimeError(f"Knowledge base {KNOWLEDGE_NAME} was not discovered")

    print(f"Health: {health_response.json()['status']}")
    print(f"Agent: {AGENT_ID}")
    print(f"Knowledge base: {KNOWLEDGE_NAME}")


# ---------------------------------------------------------------------------
# Run Knowledge REST Lifecycle
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    marker = f"control-plane-{uuid4().hex[:8]}"
    content_id: str | None = None
    deleted = False

    with httpx.Client(base_url=BASE_URL, timeout=120.0) as http_client:
        verify_server(http_client)

        try:
            upload_response = http_client.post(
                "/knowledge/content",
                data={
                    "name": f"AgentOS REST note {marker}",
                    "description": "Temporary content for the REST lifecycle.",
                    "text_content": (
                        f"The deployment marker is {marker}. AgentOS provides "
                        "one control plane for agent applications."
                    ),
                    "metadata": json.dumps(
                        {"source": "10_knowledge", "marker": marker}
                    ),
                },
            )
            if upload_response.status_code != 202:
                upload_response.raise_for_status()
                raise RuntimeError("Knowledge upload did not return 202")

            uploaded = upload_response.json()
            content_id = uploaded["id"]
            print(f"Upload status: {upload_response.status_code}")
            print(f"Content ID: {content_id}")

            final_status = wait_until_processed(http_client, content_id)

            list_response = http_client.get(
                "/knowledge/content",
                params={"limit": 20, "page": 1},
            )
            list_response.raise_for_status()
            listing = list_response.json()
            listed_ids = {item["id"] for item in listing["data"]}
            if content_id not in listed_ids:
                raise RuntimeError("Uploaded content was missing from the list")

            search_response = http_client.post(
                "/knowledge/search",
                json={
                    "query": marker,
                    "max_results": 5,
                    "meta": {"limit": 5, "page": 1},
                },
            )
            search_response.raise_for_status()
            search = search_response.json()
            matching_results = [
                result for result in search["data"] if marker in result["content"]
            ]
            if not matching_results:
                raise RuntimeError("Semantic search did not return uploaded content")

            delete_response = http_client.delete(f"/knowledge/content/{content_id}")
            delete_response.raise_for_status()
            deleted = True

            missing_response = http_client.get(f"/knowledge/content/{content_id}")
            if missing_response.status_code != 404:
                raise RuntimeError("Deleted content was still retrievable")

            print(f"Final processing status: {final_status['status']}")
            print(f"Listed content count: {listing['meta']['total_count']}")
            print(f"Search result count: {search['meta']['total_count']}")
            print(f"Matched marker: {marker}")
            print(f"Delete status: {delete_response.status_code}")
            print(f"Follow-up GET status: {missing_response.status_code}")
        finally:
            if content_id is not None and not deleted:
                http_client.delete(f"/knowledge/content/{content_id}")
