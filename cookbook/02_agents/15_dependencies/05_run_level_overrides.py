"""
Run Level Overrides
=============================

Dependencies merge: class-level dependencies provide defaults, and
`agent.run(dependencies=...)` overrides them per-run. Run-level wins on
key conflicts; non-conflicting keys merge.

Pitfall: this is a SHALLOW merge. Nested dicts at the same key are
replaced wholesale, not deep-merged.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    dependencies={
        "tenant": "acme-inc",
        "tone": "professional",
        "max_results": 10,
    },
    add_dependencies_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== Run 1: defaults from class-level dependencies ===")
    agent.print_response("Which configuration values are you using?")

    print("\n=== Run 2: override 'tone' and add new key 'audience' ===")
    agent.print_response(
        "Which configuration values are you using?",
        dependencies={"tone": "casual", "audience": "engineers"},
    )
