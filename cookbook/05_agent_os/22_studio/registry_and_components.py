"""
Inspect Registry resources and manage persisted components
==========================================================

The Registry endpoint lists code-defined primitives. The Components endpoints
manage versioned Agent, Team, and Workflow configurations in the AgentOS
database. The demo walks the 3.0 lifecycle over HTTP: create a draft, observe
that dispatch refuses it, append a guarded config version, publish, archive
with DELETE, and bring it back with the restore route.

Prerequisites: none for the HTTP demo; provider keys are needed only to run the catalog Agent
Run: .venvs/demo/bin/python cookbook/05_agent_os/22_studio/registry_and_components.py
Try: run this file with --demo in another terminal
"""

import argparse
import os
from pathlib import Path
from uuid import uuid4

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools

# ---------------------------------------------------------------------------
# Create Registry and Components AgentOS
# ---------------------------------------------------------------------------

PORT = int(os.getenv("PORT", "7777"))
BASE_URL = os.getenv("AGENT_OS_BASE_URL", f"http://127.0.0.1:{PORT}")

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
    id="registry-components-os",
    name="Registry and Components AgentOS",
    description="Read-only Registry discovery plus persisted component lifecycle.",
    agents=[catalog_agent],
    registry=registry,
    db=db,
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Registry and Components HTTP Demo
# ---------------------------------------------------------------------------


def run_demo() -> None:
    """List registry resources and complete one component lifecycle."""
    component_id = f"registry-lifecycle-agent-{uuid4().hex[:8]}"
    component_name = "Registry Lifecycle Agent"
    component_config = Agent(
        id=component_id,
        name=component_name,
        model=openai_model,
        instructions="Answer catalog questions in one sentence.",
    ).to_dict()

    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
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

        # 1. Create the component with a DRAFT version 1. A draft has no
        #    current_version: it is readable and editable, never dispatchable.
        response = client.post(
            "/components",
            json={
                "component_id": component_id,
                "component_type": "agent",
                "name": component_name,
                "description": "Created through the Components API.",
                "metadata": {"owner": "cookbook"},
                "config": component_config,
                "stage": "draft",
                "label": "initial",
            },
        )
        response.raise_for_status()
        created = response.json()
        if response.status_code != 201 or created.get("current_version") is not None:
            raise RuntimeError(f"Unexpected create response: {created}")

        # 2. A draft-only component is not runnable: the run route answers 404
        #    until a version is published. (An explicit 'version' form field
        #    on this route previews an exact draft version; it is owner- or
        #    admin-gated and would invoke the model, so it is not used here.)
        run_response = client.post(
            f"/agents/{component_id}/runs",
            data={"message": "Are you live yet?", "stream": "false"},
        )
        if run_response.status_code != 404:
            raise RuntimeError(
                f"Expected 404 for a draft-only component, got {run_response.status_code}"
            )

        list_response = client.get(
            "/components",
            params={"component_type": "agent", "limit": 100},
        )
        list_response.raise_for_status()
        listed_ids = {item["component_id"] for item in list_response.json()["data"]}
        if component_id not in listed_ids:
            raise RuntimeError("Created component was missing from the filtered list")

        # 3. Append config version 2 with a compare-and-set guard: the write
        #    succeeds only if the latest version is still the one we read.
        append_response = client.post(
            f"/components/{component_id}/configs",
            json={
                "config": component_config,
                "stage": "draft",
                "label": "guarded-append",
                "guard": {"latest_version": 1},
            },
        )
        append_response.raise_for_status()
        appended = append_response.json()
        if appended["version"] != 2:
            raise RuntimeError(f"Expected appended version 2, got {appended}")

        # The same guard is now stale: the latest version is 2, so a second
        # append claiming latest_version 1 is refused with 409.
        stale_response = client.post(
            f"/components/{component_id}/configs",
            json={
                "config": component_config,
                "stage": "draft",
                "guard": {"latest_version": 1},
            },
        )
        if stale_response.status_code != 409:
            raise RuntimeError(
                f"Expected 409 for a stale guard, got {stale_response.status_code}"
            )

        # 4. Publish draft version 2: PATCH with stage 'published' promotes it
        #    and makes it the current (dispatchable) version.
        publish_response = client.patch(
            f"/components/{component_id}/configs/2",
            json={"stage": "published"},
        )
        publish_response.raise_for_status()

        config_response = client.get(f"/components/{component_id}/configs/current")
        config_response.raise_for_status()
        current_config = config_response.json()
        if current_config["version"] != 2 or current_config["stage"] != "published":
            raise RuntimeError(f"Unexpected current config: {current_config}")

        update_response = client.patch(
            f"/components/{component_id}",
            json={
                "name": "Updated Registry Lifecycle Agent",
                "description": "Updated through PATCH /components/{component_id}.",
                "metadata": {"owner": "cookbook", "reviewed": True},
            },
        )
        update_response.raise_for_status()
        updated = update_response.json()
        if updated["name"] != "Updated Registry Lifecycle Agent":
            raise RuntimeError(f"Component update did not persist: {updated}")

        # 5. DELETE archives: the id stays reserved and history survives, but
        #    the component stops resolving.
        delete_response = client.delete(f"/components/{component_id}")
        if delete_response.status_code != 204:
            raise RuntimeError(
                f"Expected DELETE 204, got {delete_response.status_code}"
            )
        if client.get(f"/components/{component_id}").status_code != 404:
            raise RuntimeError("Archived component remained visible")

        # 6. The restore route reverses the archive at the version that was
        #    live when it was archived.
        restore_response = client.post(f"/components/{component_id}/restore")
        restore_response.raise_for_status()
        restored = restore_response.json()
        if restored.get("current_version") != 2:
            raise RuntimeError(f"Unexpected restore response: {restored}")

    print(f"Registry resources: {registry_payload['meta']['total_count']}")
    print(f"Created: {created['component_id']} (draft, no current version)")
    print("Draft dispatch: HTTP 404 before publish")
    print(f"Guarded append: v{appended['version']}; stale guard: HTTP 409")
    print(f"Current config: v{current_config['version']} ({current_config['stage']})")
    print(f"Updated name: {updated['name']}")
    print("Archive: HTTP 204; follow-up GET: HTTP 404")
    print(f"Restored: {restored['component_id']} v{restored['current_version']}")


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
