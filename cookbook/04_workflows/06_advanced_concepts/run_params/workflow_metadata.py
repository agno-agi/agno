"""
Workflow Metadata
=================

Demonstrates passing metadata from the workflow level through to downstream agents.

Metadata set at the workflow level is propagated through RunContext to every agent
in the pipeline. This is useful for tagging runs, tracking experiments, or passing
configuration that every agent should see.

Metadata merges follow a precedence rule:
  - Workflow-level metadata (self.metadata) wins on key conflicts
  - Call-site metadata fills in the rest
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create a tool that reads metadata from RunContext
# ---------------------------------------------------------------------------


def check_metadata(run_context: RunContext) -> str:
    """Return the metadata available in this run."""
    if run_context.metadata:
        items = [f"  {k}: {v}" for k, v in run_context.metadata.items()]
        return "Run metadata:\n" + "\n".join(items)
    return "No metadata available."


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
metadata_agent = Agent(
    name="Metadata Inspector",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[check_metadata],
    instructions=[
        "You are a helpful assistant that can inspect run metadata.",
        "When asked, call the check_metadata tool and report what you find.",
    ],
)

# ---------------------------------------------------------------------------
# Create Steps
# ---------------------------------------------------------------------------
inspect_step = Step(
    name="Inspect Metadata",
    description="Inspect the metadata propagated from the workflow",
    agent=metadata_agent,
)

# ---------------------------------------------------------------------------
# Create Workflow with class-level metadata
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Metadata Propagation Demo",
    steps=[inspect_step],
    # Class-level metadata: always present in every run
    metadata={"project": "acme", "tier": "production"},
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Example 1: Class-level metadata only
    print("=== Example 1: Class-level metadata ===")
    workflow.print_response(
        input="What metadata is available in this run?",
    )

    # Example 2: Call-site metadata merged with class-level
    # Class-level wins on conflicts (project stays "acme")
    print("\n=== Example 2: Merged metadata (call-site + class-level) ===")
    workflow.print_response(
        input="What metadata is available in this run?",
        metadata={"experiment": "v2", "project": "override-attempt"},
    )
