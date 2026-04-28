"""
Static Dependencies
=============================

Inject plain values (no callables) as dependencies. Useful for tenant config,
feature flags, and request-scoped settings that do not need to be computed.

Pitfall: dependencies are read once per run; mutating the dict after the
agent is created has no effect on in-flight runs.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    dependencies={
        "tenant_name": "acme-inc",
        "feature_flags": {"new_ui": True, "beta_search": False},
        "max_results": 10,
    },
    add_dependencies_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("Summarize my configuration. Which feature flags are enabled?")
