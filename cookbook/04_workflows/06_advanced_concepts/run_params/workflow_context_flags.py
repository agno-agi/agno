"""
Workflow Context Flags
======================

Demonstrates setting context control flags at the workflow level to propagate
to all downstream agents.

These flags control what additional context each agent receives:
  - add_dependencies_to_context: Include dependencies as context
  - add_session_state_to_context: Include session state as context
  - add_history_to_context: Include chat history as context
  - debug_mode: Enable debug logging

Flags set at the workflow level apply to all agents in the pipeline unless
overridden at the call site. A None value means the agent uses its own default.
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
analyzer = Agent(
    name="Analyzer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are an analyzer that processes text and provides a brief summary.",
        "Check your additional context for any configuration or state.",
        "Include a note about what context you received.",
    ],
)

reviewer = Agent(
    name="Reviewer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a reviewer that checks the analysis from the previous step.",
        "Check your additional context for any configuration or state.",
        "Provide a brief review and note what context you received.",
    ],
)

# ---------------------------------------------------------------------------
# Create Steps
# ---------------------------------------------------------------------------
analyze_step = Step(
    name="Analyze",
    description="Analyze the input text",
    agent=analyzer,
)

review_step = Step(
    name="Review",
    description="Review the analysis",
    agent=reviewer,
)

# ---------------------------------------------------------------------------
# Create Workflow with context flags
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Context Flags Demo",
    steps=[analyze_step, review_step],
    # These flags propagate to ALL agents in the workflow
    dependencies={"model_version": "v2", "region": "us-east-1"},
    add_dependencies_to_context=True,
    session_state={"task_count": 0, "last_topic": None},
    add_session_state_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Example 1: Workflow-level flags propagated to both agents
    print("=== Example 1: Workflow-level context flags ===")
    print("Both agents will see dependencies and session state in their context.\n")
    workflow.print_response(
        input="Analyze the impact of AI on healthcare in 2025.",
    )

    # Example 2: Call-site override with debug_mode
    print("\n=== Example 2: Call-site debug_mode override ===")
    print("Adding debug_mode=True at the call site.\n")
    workflow.print_response(
        input="Analyze the impact of AI on education.",
        debug_mode=True,
    )

    # Example 3: Async run with call-site flag overrides
    print("\n=== Example 3: Async with call-site overrides ===")
    print("Overriding add_dependencies_to_context=False at call site.\n")
    asyncio.run(
        workflow.aprint_response(
            input="Analyze the impact of AI on finance.",
            add_dependencies_to_context=False,
        )
    )
