"""
Callable Tools Factory
======================
Pass a function as `tools` instead of a list. The function is called
at the start of each run, so the toolset can vary per user or session.

The factory receives parameters by name via signature inspection:
- agent: the Agent instance
- run_context: the current RunContext (has user_id, session_id, etc.)
- session_state: the current session state dict

Results are cached per user_id (or session_id) by default.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run import RunContext

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def search_web(query: str) -> str:
    """Search the web for information."""
    return f"Search results for: {query}"


def search_internal_docs(query: str) -> str:
    """Search internal documentation (admin only)."""
    return f"Internal doc results for: {query}"


def get_account_balance(account_id: str) -> str:
    """Get account balance (finance only)."""
    return f"Balance for {account_id}: $42,000"


# ---------------------------------------------------------------------------
# Callable Factory
# ---------------------------------------------------------------------------


def tools_for_user(run_context: RunContext):
    """Return different tools based on the user's role stored in session_state."""
    role = (run_context.session_state or {}).get("role", "viewer")
    print(f"--> Resolving tools for role: {role}")

    base_tools = [search_web]
    if role == "admin":
        base_tools.append(search_internal_docs)
    if role in ("admin", "finance"):
        base_tools.append(get_account_balance)

    return base_tools


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=tools_for_user,
    instructions=[
        "You are a helpful assistant.",
        "Use the tools available to you to answer the user's question.",
    ],
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Run 1: viewer role - only search_web available
    # Each user_id gets its own cached toolset
    print("=== Run as viewer ===")
    agent.print_response(
        "Search for recent news about AI agents",
        user_id="viewer_user",
        session_state={"role": "viewer"},
        stream=True,
    )

    # Run 2: admin role - all tools available
    # Different user_id means the factory is called again with new context
    print("\n=== Run as admin ===")
    agent.print_response(
        "Search internal docs for the deployment guide and check account balance for ACC-001",
        user_id="admin_user",
        session_state={"role": "admin"},
        stream=True,
    )
