"""Using the learnings REST API endpoints directly.

This example demonstrates:
- Creating a learning record via POST /learnings
- Listing learnings via GET /learnings
- Listing the users that own learnings via GET /learnings/users
- Fetching a single learning via GET /learnings/{id}
- Updating content/metadata via PATCH /learnings/{id}
- Deleting via DELETE /learnings/{id}

Requires: a running AgentOS server. Start one with:

    .venvs/demo/bin/python cookbook/05_agent_os/learnings/learnings_with_agentos.py

Then in another terminal:

    .venvs/demo/bin/python cookbook/05_agent_os/learnings/rest_api_learnings.py
"""

import httpx

BASE_URL = "http://127.0.0.1:7777"

client = httpx.Client(base_url=BASE_URL, timeout=30)


def main():
    # =========================================================================
    # 1. Create a learning record
    # =========================================================================
    print("=== Create Learning ===\n")
    resp = client.post(
        "/learnings",
        json={
            "learning_type": "user_profile",
            "namespace": "global",
            "user_id": "demo-user",
            "content": {
                "name": "Yash",
                "preferences": {"language": "Python", "tone": "concise"},
            },
            "metadata": {"source": "rest-api-demo"},
        },
    )
    resp.raise_for_status()
    learning = resp.json()
    learning_id = learning["learning_id"]
    print(f"Created: {learning_id}")
    print(f"  Type: {learning['learning_type']}")
    print(f"  Content: {learning['content']}")

    # =========================================================================
    # 2. List learnings (with filters)
    # =========================================================================
    print("\n=== List Learnings ===\n")
    resp = client.get(
        "/learnings", params={"user_id": "demo-user", "limit": 10, "page": 1}
    )
    resp.raise_for_status()
    result = resp.json()
    records = result["data"]
    meta = result["meta"]
    print(
        "Page {} of {} (total: {})\n".format(
            meta["page"], meta["total_pages"], meta["total_count"]
        )
    )
    for r in records:
        print(f"  {r['learning_id']} -> {r['learning_type']} (user={r['user_id']})")

    # =========================================================================
    # 3. List the users that own learnings
    # =========================================================================
    # Entry point for a per-user view: list users first, then drill into a
    # single user's learnings via GET /learnings?user_id=...
    print("\n=== List Learning Users ===\n")
    resp = client.get("/learnings/users", params={"learning_type": "user_profile"})
    resp.raise_for_status()
    for u in resp.json()["data"]:
        print(
            "  user={} last_updated={}".format(
                u["user_id"], u["last_learning_updated_at"]
            )
        )

    # =========================================================================
    # 4. Fetch a single learning
    # =========================================================================
    print("\n=== Get Learning ===\n")
    resp = client.get(f"/learnings/{learning_id}")
    resp.raise_for_status()
    detail = resp.json()
    print(f"  ID: {detail['learning_id']}")
    print(f"  Namespace: {detail['namespace']}")
    print(f"  Content keys: {list((detail.get('content') or {}).keys())}")

    # =========================================================================
    # 5. Update content + metadata (full replace)
    # =========================================================================
    print("\n=== Update Learning ===\n")
    resp = client.patch(
        f"/learnings/{learning_id}",
        json={
            "content": {
                "name": "Yash",
                "preferences": {
                    "language": "Python",
                    "tone": "concise",
                    "loves": "agentic frameworks",
                },
            },
            "metadata": {"source": "rest-api-demo", "version": 2},
        },
    )
    resp.raise_for_status()
    updated = resp.json()
    print(f"  Updated content: {updated['content']}")
    print(f"  Updated metadata: {updated['metadata']}")

    # =========================================================================
    # 6. Delete the learning
    # =========================================================================
    print("\n=== Delete Learning ===\n")
    resp = client.delete(f"/learnings/{learning_id}")
    resp.raise_for_status()
    print(f"  Deleted (status {resp.status_code})")

    # Verify it's gone
    resp = client.get(f"/learnings/{learning_id}")
    print(f"  Follow-up GET status: {resp.status_code} (expect 404)")

    print("\nDone.")


if __name__ == "__main__":
    main()
