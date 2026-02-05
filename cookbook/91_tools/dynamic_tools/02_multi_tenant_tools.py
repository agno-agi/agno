"""
Multi-Tenant Tools with Callable Tools
======================================
This example demonstrates how to create tenant-isolated tool instances
for SaaS applications. Each organization gets their own tool resources,
completely isolated from other tenants.

Use case:
- SaaS platforms where each customer (tenant) needs isolated data
- Enterprise deployments with strict data separation requirements
- Multi-tenant applications with per-tenant customization

Key concepts:
- run_context.dependencies: Contains tenant_id from your auth layer
- run_context.session_state: Alternative source for tenant context
- Complete data isolation at the tool level
- callable_tools_cache_key: Cache tools per tenant_id (avoid cross-tenant reuse)
"""

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Union

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.tools.duckdb import DuckDbTools
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit

# Create a temp directory for tenant databases
TENANT_DATA_DIR = Path(tempfile.mkdtemp(prefix="tenant_dbs_"))


def _safe_tenant_id(tenant_id: str) -> str:
    """Sanitize tenant_id for safe directory/file names."""
    return (
        tenant_id.strip()
        .lower()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace("..", "_")
    )


def get_tenant_cache_key(run_context: RunContext) -> str:
    """Cache tools per tenant_id so different tenants never share tool instances."""
    dependencies = run_context.dependencies or {}
    session_state = run_context.session_state or {}
    tenant_id = dependencies.get("tenant_id") or session_state.get("tenant_id")
    return _safe_tenant_id(str(tenant_id)) if tenant_id else run_context.session_id


# ============================================================================
# Tools Factory Function with Tenant Context
# ============================================================================


def get_tenant_tools(
    run_context: RunContext,
) -> List[Union[Toolkit, Function, Dict[str, Any]]]:
    """Create tenant-specific tools at runtime.

    In a real SaaS application:
    - tenant_id would come from your authentication middleware
    - You might validate the tenant exists and is active
    - You could apply tenant-specific configurations

    Args:
        run_context: Runtime context with dependencies containing tenant_id

    Returns:
        List of tools configured for this specific tenant.
    """
    # Get tenant_id from dependencies (set by your auth layer)
    # or fall back to session_state (for testing)
    dependencies = run_context.dependencies or {}
    session_state = run_context.session_state or {}

    tenant_id = dependencies.get("tenant_id") or session_state.get("tenant_id")

    if not tenant_id:
        raise ValueError(
            "tenant_id is required. Pass it via dependencies or session_state. "
            "Example: agent.run(message, dependencies={'tenant_id': 'acme-corp'})"
        )

    print(f"Initializing tools for tenant: {tenant_id}")

    safe_tenant_id = _safe_tenant_id(str(tenant_id))

    # Create tenant-specific directory
    tenant_dir = TENANT_DATA_DIR / safe_tenant_id
    tenant_dir.mkdir(parents=True, exist_ok=True)

    # Each tenant gets their own database
    db_path = str(tenant_dir / "tenant_data.db")
    print(f"Tenant database: {db_path}")

    return [
        DuckDbTools(
            db_path=db_path,
            read_only=False,
        ),
    ]


# ============================================================================
# Create the Agent with Callable Tools
# ============================================================================
agent = Agent(
    name="Tenant Database Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    # Pass the callable - tools are created per-run with tenant context
    tools=get_tenant_tools,
    # Cache per tenant_id to avoid cross-tenant reuse when cache_callables=True.
    callable_tools_cache_key=get_tenant_cache_key,
    instructions="""\
You are a database assistant for a multi-tenant SaaS application.
Each tenant has their own isolated database.

Help users:
1. Create and manage tables
2. Insert and query data
3. All operations are scoped to their tenant's database
""",
    markdown=True,
)


# ============================================================================
# Main: Demonstrate Tenant Isolation
# ============================================================================
if __name__ == "__main__":
    print(f"Tenant databases will be stored in: {TENANT_DATA_DIR}")

    # Tenant A: Acme Corp creates their data
    print("\n" + "=" * 60)
    print("Tenant: acme-corp - Creating inventory table")
    print("=" * 60)
    agent.print_response(
        "Create a table called inventory with columns: sku (varchar primary key), "
        "name (varchar), quantity (integer). Insert: SKU001, Widget, 100.",
        dependencies={"tenant_id": "acme-corp"},
        stream=True,
    )

    # Tenant B: Globex creates their data
    print("\n" + "=" * 60)
    print("Tenant: globex-inc - Creating employees table")
    print("=" * 60)
    agent.print_response(
        "Create a table called employees with columns: id (integer primary key), "
        "name (varchar), department (varchar). Insert: 1, John Smith, Engineering.",
        dependencies={"tenant_id": "globex-inc"},
        stream=True,
    )

    # Verify isolation: Acme Corp should only see inventory
    print("\n" + "=" * 60)
    print("Tenant: acme-corp - Checking tables (should only see inventory)")
    print("=" * 60)
    agent.print_response(
        "List all tables in my database",
        dependencies={"tenant_id": "acme-corp"},
        stream=True,
    )

    # Verify isolation: Globex should only see employees
    print("\n" + "=" * 60)
    print("Tenant: globex-inc - Checking tables (should only see employees)")
    print("=" * 60)
    agent.print_response(
        "List all tables in my database",
        dependencies={"tenant_id": "globex-inc"},
        stream=True,
    )

    # Show data directories
    print("\n" + "=" * 60)
    print("Tenant data directories:")
    print("=" * 60)
    for tenant_dir in TENANT_DATA_DIR.iterdir():
        print(f"  - {tenant_dir.name}/")
        for file in tenant_dir.iterdir():
            print(f"      {file.name}")
