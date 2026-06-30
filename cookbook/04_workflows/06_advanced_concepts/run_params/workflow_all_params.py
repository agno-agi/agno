"""
Workflow All Run Params
=======================

Demonstrates using all workflow run-level parameters together in a realistic
content creation pipeline.

This example shows:
  - metadata: Tagging runs with project and environment info
  - dependencies: Injecting configuration (tone, word count, target audience)
  - add_dependencies_to_context: Making config visible to agents
  - add_session_state_to_context: Making session state visible to agents
"""

import asyncio

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
researcher = Agent(
    name="Content Researcher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a content researcher.",
        "Research the given topic and provide 3-5 key points.",
        "Check your context for configuration like target audience and tone.",
        "Tailor your research to the specified audience if provided.",
        "Be concise and factual.",
    ],
)

writer = Agent(
    name="Content Writer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a content writer.",
        "Take the research from the previous step and write a short article.",
        "Check your context for configuration like tone, word count, and target audience.",
        "Follow the specified tone and word count if provided.",
        "Write engaging, clear content.",
    ],
)

# ---------------------------------------------------------------------------
# Create Steps
# ---------------------------------------------------------------------------
research_step = Step(
    name="Research",
    description="Research the topic",
    agent=researcher,
)

writing_step = Step(
    name="Write",
    description="Write the article based on research",
    agent=writer,
)

# ---------------------------------------------------------------------------
# Create Workflow with all params
# ---------------------------------------------------------------------------
content_pipeline = Workflow(
    name="Content Pipeline",
    steps=[research_step, writing_step],
    # Workflow-level metadata (always present)
    metadata={"project": "blog", "version": "1.0"},
    # Workflow-level dependencies (default configuration)
    dependencies={
        "tone": "professional",
        "max_words": 200,
        "target_audience": "developers",
    },
    # Context flags: all agents see dependencies and session state
    add_dependencies_to_context=True,
    add_session_state_to_context=True,
    # Initial session state
    session_state={"articles_written": 0},
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Example 1: Using workflow defaults
    print("=== Example 1: Workflow defaults ===")
    print("Using default tone=professional, audience=developers\n")
    content_pipeline.print_response(
        input="Write about the benefits of type hints in Python.",
    )

    # Example 2: Run level overrides for a different audience
    print("\n=== Example 2: Run level overrides ===")
    print("Overriding: tone=casual, audience=beginners\n")
    content_pipeline.print_response(
        input="Write about getting started with Python.",
        # Override specific dependencies at call site
        dependencies={"tone": "casual", "target_audience": "beginners"},
        # Add call-site metadata
        metadata={"campaign": "onboarding"},
    )

    # Example 3: Async execution
    print("\n=== Example 3: Async execution ===")
    asyncio.run(
        content_pipeline.aprint_response(
            input="Write about async programming in Python.",
        )
    )
