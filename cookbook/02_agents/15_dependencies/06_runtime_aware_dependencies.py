"""
Runtime-Aware Dependencies
=============================

Dependency resolvers can opt into the agent and run context by declaring
`agent` and/or `run_context` parameters. The framework inspects the
signature and passes them in automatically.

This is the cleanest way to fetch user-specific data from the resolver:
read `run_context.user_id` or `run_context.session_id` to drive the
lookup, and the rest of the agent pipeline sees the resolved value.

Pitfall: parameter names matter — only `agent` and `run_context` are
injected. Other names are ignored.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.run import RunContext

USER_PROFILES = {
    "user_alice": {"name": "Alice", "tier": "enterprise"},
    "user_bob": {"name": "Bob", "tier": "free"},
}


def get_user_profile(run_context: RunContext) -> dict:
    user_id = run_context.user_id or "unknown"
    return USER_PROFILES.get(user_id, {"name": "Unknown", "tier": "guest"})


def describe_session(run_context: RunContext, agent: Agent) -> str:
    return f"agent={agent.name}, session={run_context.session_id}"


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    name="ProfileAware",
    model=OpenAIResponses(id="gpt-5.4"),
    dependencies={
        "user_profile": get_user_profile,
        "session_info": describe_session,
    },
    add_dependencies_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Run as user_alice ===")
    agent.print_response(
        "Greet me by name and mention my tier.",
        user_id="user_alice",
        session_id="alice_session",
    )

    print("\n=== Run as user_bob ===")
    agent.print_response(
        "Greet me by name and mention my tier.",
        user_id="user_bob",
        session_id="bob_session",
    )
