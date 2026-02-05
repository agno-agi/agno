"""
Multi-Tenant Knowledge with Callable Knowledge
==============================================
This example demonstrates a multi-tenant architecture where each organization
(tenant) has completely isolated knowledge bases. This pattern is essential
for SaaS applications where data isolation is critical.

Architecture:
------------
- Each tenant gets their own vector database namespace
- Users within a tenant share the same knowledge base
- Tenant ID comes from session_state or dependencies at runtime
- Complete data isolation between tenants

Benefits over metadata filtering:
--------------------------------
1. **Security**: Physical isolation, not just query-time filtering
2. **Performance**: Smaller indexes per tenant = faster queries
3. **Compliance**: Easy to demonstrate data isolation for audits
4. **Data lifecycle**: Simple tenant offboarding (drop partition)

Example usage:
- Organization "acme" has their internal docs
- Organization "globex" has different docs
- Each org's users only see their org's documents
"""

from typing import Any, Dict

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.vectordb.chroma import ChromaDb

# ============================================================================
# Multi-Tenant Knowledge Factory
# ============================================================================


def get_tenant_knowledge(
    agent: Agent,
    session_state: Dict[str, Any],
    run_context: RunContext,
) -> Knowledge:
    """Create a tenant-specific knowledge base at runtime.

    This function demonstrates accessing multiple sources of context:
    - agent: The agent instance (for accessing agent config)
    - session_state: Persistent state across the session
    - run_context: Runtime context with user_id, dependencies, etc.

    Tenant ID resolution priority:
    1. From dependencies (passed at runtime)
    2. From session_state (persisted across runs)
    3. Default to "public" tenant

    Args:
        agent: The Agent instance.
        session_state: Current session state dictionary.
        run_context: Runtime context with dependencies, user_id, etc.

    Returns:
        Knowledge instance configured for this tenant.
    """
    # Try to get tenant_id from various sources
    tenant_id = None

    # 1. Check dependencies (highest priority - explicitly passed)
    if run_context.dependencies:
        tenant_id = run_context.dependencies.get("tenant_id")

    # 2. Check session_state (persisted from previous runs)
    if not tenant_id and session_state:
        tenant_id = session_state.get("tenant_id")

    # 3. Default to public tenant
    if not tenant_id:
        tenant_id = "public"

    # Sanitize for use in paths/collection names
    safe_tenant_id = tenant_id.lower().replace(" ", "_").replace("-", "_")

    print(f"Resolving knowledge for tenant: {tenant_id}")
    print(f"  - User: {run_context.user_id or 'anonymous'}")
    print(f"  - Session: {run_context.session_id}")

    # Create tenant-isolated knowledge base
    return Knowledge(
        name=f"{tenant_id} Knowledge Base",
        vector_db=ChromaDb(
            name=f"tenant_{safe_tenant_id}",
            collection=f"tenant_{safe_tenant_id}_docs",
            path=f"tmp/chromadb/tenants/{safe_tenant_id}",
            persistent_client=True,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
        max_results=5,
    )


# ============================================================================
# Create the Multi-Tenant Agent
# ============================================================================


def get_tenant_cache_key(run_context: RunContext) -> str:
    """Cache knowledge per tenant_id so users in the same tenant share it."""
    dependencies = run_context.dependencies or {}
    session_state = run_context.session_state or {}
    tenant_id = (
        dependencies.get("tenant_id") or session_state.get("tenant_id") or "public"
    )
    return str(tenant_id)


agent = Agent(
    name="Enterprise Knowledge Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    # Callable knowledge - resolved per-run based on tenant context
    knowledge=get_tenant_knowledge,
    # Cache per tenant_id instead of per user_id.
    callable_knowledge_cache_key=get_tenant_cache_key,
    search_knowledge=True,
    instructions="""\
You are an enterprise knowledge assistant serving multiple organizations.
Each organization has their own isolated knowledge base.

Guidelines:
1. Search the organization's knowledge base to answer questions
2. Never reference or hint at other organizations' data
3. If information isn't found, suggest contacting the admin
4. Be professional and context-aware
""",
    markdown=True,
)


# ============================================================================
# Helper Functions
# ============================================================================


def load_tenant_content(tenant_id: str, content_url: str, content_name: str):
    """Load content into a tenant's knowledge base."""
    run_context = RunContext(
        run_id="load",
        session_id="load",
        user_id="system",
        dependencies={"tenant_id": tenant_id},
    )

    knowledge = get_tenant_knowledge(
        agent=agent,
        session_state={},
        run_context=run_context,
    )

    print(f"Loading '{content_name}' for tenant '{tenant_id}'...")
    knowledge.insert(name=content_name, url=content_url)
    print("Content loaded successfully\n")


def query_as_tenant(tenant_id: str, user_id: str, query: str):
    """Query the agent as a user from a specific tenant."""
    print("\n" + "=" * 60)
    print(f"Tenant: {tenant_id} | User: {user_id}")
    print(f"Query: {query}")
    print("=" * 60)

    agent.print_response(
        query,
        user_id=user_id,
        dependencies={"tenant_id": tenant_id},
        stream=True,
    )


# ============================================================================
# Main: Demonstrate Multi-Tenant Isolation
# ============================================================================
if __name__ == "__main__":
    # Setup: Load different content for different tenants
    print("Setting up tenant knowledge bases...\n")

    load_tenant_content(
        tenant_id="acme",
        content_url="https://docs.agno.com/introduction.md",
        content_name="ACME Internal Docs",
    )

    load_tenant_content(
        tenant_id="globex",
        content_url="https://docs.agno.com/agents/introduction.md",
        content_name="Globex Agent Guidelines",
    )

    # Demonstrate tenant isolation
    print("\n" + "#" * 60)
    print("# DEMONSTRATING TENANT ISOLATION")
    print("#" * 60)

    # ACME user queries - sees only ACME docs
    query_as_tenant(
        tenant_id="acme",
        user_id="alice@acme.com",
        query="What can you tell me about our documentation?",
    )

    # Globex user queries - sees only Globex docs
    query_as_tenant(
        tenant_id="globex",
        user_id="bob@globex.com",
        query="What are the guidelines for agents?",
    )

    # ACME user asking about agents - won't find Globex content
    query_as_tenant(
        tenant_id="acme",
        user_id="alice@acme.com",
        query="What are the agent guidelines?",
    )

    print("\n" + "#" * 60)
    print("# USING SESSION STATE FOR TENANT CONTEXT")
    print("#" * 60)

    # Alternative: Pass tenant via session_state
    # Useful when tenant is determined once per session
    print("\nQuerying with tenant_id in session_state:")
    agent.print_response(
        "What documentation do we have?",
        user_id="charlie@acme.com",
        session_state={"tenant_id": "acme"},
        stream=True,
    )
