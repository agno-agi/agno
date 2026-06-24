"""
Workflow Dependencies
=====================

Demonstrates passing dependencies from the workflow level through to downstream agents.

Dependencies are key-value pairs injected into RunContext. When add_dependencies_to_context
is True, the agent includes them as additional context sent to the model.

This is useful for injecting configuration, database connections, or other
shared resources that every agent in the workflow should have access to.

Dependency merges follow a precedence rule:
  - Run level dependencies win on key conflicts
  - Workflow-level dependencies (self.dependencies) fill in the rest
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
config_aware_agent = Agent(
    name="Config-Aware Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a helpful assistant that operates based on the provided configuration.",
        "Check your additional context for configuration details.",
        "Acknowledge the configuration you see and explain how you would use it.",
    ],
)

# ---------------------------------------------------------------------------
# Create Steps
# ---------------------------------------------------------------------------
process_step = Step(
    name="Process with Config",
    description="Process the input using the workflow configuration",
    agent=config_aware_agent,
)

# ---------------------------------------------------------------------------
# Create Workflow with class-level dependencies
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Dependency Injection Demo",
    steps=[process_step],
    # Class-level dependencies: available in every run
    dependencies={
        "database_url": "postgres://localhost:5432/mydb",
        "api_version": "v2",
    },
    # Enable dependency injection into agent context
    add_dependencies_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Example 1: Class-level dependencies only
    print("=== Example 1: Workflow-level dependencies ===")
    workflow.print_response(
        input="What configuration are you using? Describe the database and API version.",
    )

    # Example 2: Run level dependencies merged with class-level
    # Run level wins on conflicts (api_version becomes "v3")
    print("\n=== Example 2: Merged dependencies (call-site overrides) ===")
    workflow.print_response(
        input="What configuration are you using? Note any changes from defaults.",
        dependencies={"api_version": "v3", "feature_flag": "new_ui"},
    )
