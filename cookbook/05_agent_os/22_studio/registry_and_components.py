"""
Inspect Registry resources and manage persisted components
==========================================================

The Registry endpoint lists code-defined primitives. The Components endpoints
manage guarded, versioned Agent, Team, and Workflow configurations in the
AgentOS database. Metadata edits append a draft, publishing moves the current
pointer, and DELETE soft-archives the component with compare-and-set guards.
Components require a synchronous BaseDb; this example uses SqliteDb.

Prerequisites: none for the HTTP demo; provider keys are needed only to run the catalog Agent
Run: .venvs/demo/bin/python cookbook/05_agent_os/22_studio/registry_and_components.py
Try: run this file with --demo in another terminal
"""

import argparse
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools

# ---------------------------------------------------------------------------
# Create Registry and Components AgentOS
# ---------------------------------------------------------------------------

PORT = int(os.getenv("PORT", "7777"))
BASE_URL = os.getenv("AGENT_OS_BASE_URL", f"http://127.0.0.1:{PORT}")
OS_ID = "registry-components-os"
ADMIN_USER_ID = "components-admin"
JWT_SECRET = os.getenv(
    "JWT_VERIFICATION_KEY",
    "registry-components-development-secret-at-least-256-bits-long",
)


def make_admin_token() -> str:
    """Mint a short-lived, audience-bound token for the local HTTP demo."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": ADMIN_USER_ID,
            "aud": OS_ID,
            "scopes": ["agent_os:admin"],
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


DB_DIR = Path(__file__).parent / "tmp"
DB_DIR.mkdir(exist_ok=True)

db = SqliteDb(
    id="registry-components-db",
    db_file=str(DB_DIR / "registry_components.db"),
)

openai_model = OpenAIResponses(id="gpt-5.5")
claude_model = Claude(id="claude-sonnet-4-6")

registry = Registry(
    name="Registry and Components Catalog",
    tools=[CalculatorTools()],
    models=[openai_model, claude_model],
    dbs=[db],
)

catalog_agent = Agent(
    id="catalog-agent",
    name="Catalog Agent",
    model=openai_model,
    instructions="Explain the difference between registry primitives and persisted components.",
    db=db,
)

agent_os = AgentOS(
    id=OS_ID,
    name="Registry and Components AgentOS",
    description="Read-only Registry discovery plus a guarded persisted-component lifecycle.",
    agents=[catalog_agent],
    registry=registry,
    db=db,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        verify_audience=True,
    ),
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Registry and Components HTTP Demo
# ---------------------------------------------------------------------------


def run_demo() -> None:
    """List registry resources, append and publish a draft, then soft-archive it."""
    component_id = f"registry-crud-agent-{uuid4().hex[:8]}"
    component_name = "Registry CRUD Agent"
    component_config = Agent(
        id=component_id,
        name=component_name,
        model=openai_model,
        instructions="Answer catalog questions in one sentence.",
    ).to_dict()

    with httpx.Client(
        base_url=BASE_URL,
        timeout=60.0,
        headers={"Authorization": f"Bearer {make_admin_token()}"},
    ) as client:
        registry_response = client.get("/registry", params={"limit": 100})
        registry_response.raise_for_status()
        registry_payload = registry_response.json()
        resource_types = {item["type"] for item in registry_payload["data"]}
        resource_names = {item["name"] for item in registry_payload["data"]}
        if not {"tool", "model", "db"}.issubset(resource_types):
            raise RuntimeError(
                f"Registry omitted expected resource types: {resource_types}"
            )
        if not {"calculator", "gpt-5.5", "claude-sonnet-4-6"}.issubset(resource_names):
            raise RuntimeError(f"Registry omitted expected resources: {resource_names}")

        response = client.post(
            "/components",
            json={
                "component_id": component_id,
                "component_type": "agent",
                "name": component_name,
                "description": "Created through the Components API.",
                "metadata": {"owner": "cookbook"},
                "config": component_config,
                "stage": "published",
                "label": "initial",
            },
        )
        response.raise_for_status()
        created = response.json()
        if response.status_code != 201 or created.get("current_version") != 1:
            raise RuntimeError(f"Unexpected create response: {created}")

        get_response = client.get(f"/components/{component_id}")
        get_response.raise_for_status()

        list_response = client.get(
            "/components",
            params={"component_type": "agent", "limit": 100},
        )
        list_response.raise_for_status()
        listed_ids = {item["component_id"] for item in list_response.json()["data"]}
        if component_id not in listed_ids:
            raise RuntimeError("Created component was missing from the filtered list")

        update_response = client.patch(
            f"/components/{component_id}",
            json={
                "name": "Updated Registry CRUD Agent",
                "description": "Updated through PATCH /components/{component_id}.",
                "metadata": {"owner": "cookbook", "reviewed": True},
                "guard": {"latest_version": 1, "current_version": 1},
            },
        )
        update_response.raise_for_status()
        draft = update_response.json()
        if (
            draft["version"] != 2
            or draft["stage"] != "draft"
            or draft["config"]["name"] != "Updated Registry CRUD Agent"
        ):
            raise RuntimeError(f"PATCH did not append the expected draft: {draft}")

        config_response = client.get(f"/components/{component_id}/configs/current")
        config_response.raise_for_status()
        pre_publish_current = config_response.json()
        if (
            pre_publish_current["version"] != 1
            or pre_publish_current["stage"] != "published"
        ):
            raise RuntimeError(
                f"Draft edit moved the current pointer: {pre_publish_current}"
            )

        publish_response = client.patch(
            f"/components/{component_id}/configs/2",
            json={
                "stage": "published",
                "guard": {"latest_version": 2, "current_version": 1},
            },
        )
        publish_response.raise_for_status()
        published = publish_response.json()
        if published["version"] != 2 or published["stage"] != "published":
            raise RuntimeError(f"Draft publication failed: {published}")

        current_response = client.get(f"/components/{component_id}")
        current_response.raise_for_status()
        current = current_response.json()
        if (
            current["current_version"] != 2
            or current["name"] != "Updated Registry CRUD Agent"
        ):
            raise RuntimeError(
                f"Published projection did not move atomically: {current}"
            )

        delete_response = client.request(
            "DELETE",
            f"/components/{component_id}",
            json={"guard": {"latest_version": 2, "current_version": 2}},
        )
        if delete_response.status_code != 204:
            raise RuntimeError(
                f"Expected archive 204, got {delete_response.status_code}"
            )
        if client.get(f"/components/{component_id}").status_code != 404:
            raise RuntimeError("Archived component remained visible")

    print(f"Registry resources: {registry_payload['meta']['total_count']}")
    print(f"Created: {created['component_id']} v{created['current_version']}")
    print(f"Appended draft: v{draft['version']} ({draft['stage']})")
    print(f"Published current: v{current['current_version']} as {current['name']}")
    print("Soft-archived component: HTTP 204; follow-up GET: HTTP 404")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the HTTP client against a server already listening on port 7777.",
    )
    args = parser.parse_args()

    if args.demo:
        run_demo()
    else:
        agent_os.serve(app=app, host="127.0.0.1", port=PORT)
