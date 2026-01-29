"""
Conditional Tools Based on User Role
====================================
This example demonstrates how to provide different tools based on
user attributes like role, permissions, or subscription tier.

Use cases:
- Different tool access for admin vs regular users
- Premium features for paid subscribers
- Role-based tool restrictions (e.g., read-only for viewers)

Key concepts:
- run_context.session_state: Contains user attributes like role
- run_context.dependencies: Can contain auth/permission info
- Conditional tool lists: Different users get different capabilities
"""

from typing import Any, Dict, List, Union

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.tools.duckdb import DuckDbTools
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit


# ============================================================================
# Custom Tools for Different Roles
# ============================================================================


def safe_calculator(expression: str) -> str:
    """Evaluate a simple math expression safely.

    Args:
        expression: A math expression like "2 + 2" or "10 * 5"

    Returns:
        The result of the calculation
    """
    # Only allow safe characters
    allowed = set("0123456789+-*/.() ")
    if not all(c in allowed for c in expression):
        return "Error: Invalid characters in expression"

    try:
        result = eval(expression)  # Safe due to character whitelist
        return f"{expression} = {result}"
    except Exception as e:
        return f"Error: {e}"


def admin_execute_query(query: str) -> str:
    """Execute any SQL query (admin only).

    This is a dangerous tool that should only be available to admins.

    Args:
        query: Raw SQL query to execute

    Returns:
        Query results or error message
    """
    return f"[ADMIN] Executed: {query}\n(This is a demo - no actual query ran)"


def export_all_data() -> str:
    """Export all system data (admin only).

    This exports sensitive data and should only be available to admins.

    Returns:
        Status message
    """
    return "[ADMIN] All data exported successfully (demo)"


# ============================================================================
# Tools Factory Function with Role-Based Access
# ============================================================================


def get_role_based_tools(
    run_context: RunContext,
) -> List[Union[Toolkit, Function, Dict[str, Any]]]:
    """Create tools based on user role.

    Different roles get different tool capabilities:
    - viewer: Read-only tools only
    - user: Standard tools
    - admin: All tools including dangerous operations

    Args:
        run_context: Runtime context with session_state containing role

    Returns:
        List of tools appropriate for the user's role.
    """
    # Get role from session_state or dependencies
    session_state = run_context.session_state or {}
    dependencies = run_context.dependencies or {}

    role = session_state.get("role") or dependencies.get("role") or "viewer"

    print(f"Configuring tools for role: {role}")

    # Base tools available to everyone
    tools: List[Union[Toolkit, Function, Dict[str, Any]]] = [
        safe_calculator,  # Safe calculation tool
    ]

    # Standard user tools
    if role in ["user", "admin"]:
        tools.append(
            DuckDbTools(
                db_path=":memory:",  # In-memory for demo
                read_only=(role == "viewer"),
            )
        )

    # Admin-only tools
    if role == "admin":
        tools.extend(
            [
                admin_execute_query,
                export_all_data,
            ]
        )

    tool_names = [getattr(t, "name", getattr(t, "__name__", str(t))) for t in tools]
    print(f"Available tools: {tool_names}")

    return tools


# ============================================================================
# Create the Agent with Callable Tools
# ============================================================================
agent = Agent(
    name="Role-Based Assistant",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=get_role_based_tools,
    instructions="""\
You are an assistant with role-based tool access.

Your available tools depend on the user's role:
- **Viewer**: Can only use the calculator
- **User**: Can use calculator and database (read/write)
- **Admin**: Full access including dangerous admin operations

Always check what tools you have available before responding.
If a user asks for something you can't do, explain that they need
a higher permission level.
""",
    markdown=True,
)


# ============================================================================
# Main: Demonstrate Role-Based Tool Access
# ============================================================================
if __name__ == "__main__":
    # Viewer role: Limited access
    print("=" * 60)
    print("Role: VIEWER")
    print("=" * 60)
    agent.print_response(
        "What tools do you have? Can you create a table?",
        session_state={"role": "viewer"},
        stream=True,
    )

    # User role: Standard access
    print("\n" + "=" * 60)
    print("Role: USER")
    print("=" * 60)
    agent.print_response(
        "What tools do you have? Can you export all data?",
        session_state={"role": "user"},
        stream=True,
    )

    # Admin role: Full access
    print("\n" + "=" * 60)
    print("Role: ADMIN")
    print("=" * 60)
    agent.print_response(
        "What tools do you have?",
        session_state={"role": "admin"},
        stream=True,
    )
