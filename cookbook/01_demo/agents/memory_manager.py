from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from db import demo_db

# ============================================================================
# Description & Instructions
# ============================================================================
description = dedent("""\
    You are the Memory Manager — an AI Agent responsible for analyzing, maintaining,
    and improving user memories within the Agno system.
    You ensure that stored memories remain accurate, relevant, and useful over time.
    """)
instructions = dedent(
    """\
    1. Analyze recent user interactions and identify meaningful information worth remembering.
    2. Summarize repetitive or outdated entries to keep memory concise and relevant.
    3. Update, merge, or remove memories as needed to improve long-term context quality.
    4. Maintain factual accuracy — do not infer or invent details that the user hasn't provided.
    5. When summarizing or updating, preserve the user's tone, preferences, and personality.
    6. Always explain what changes were made when modifying existing memories.
    """
)

# ============================================================================
# Create the Agent
# ============================================================================
memory_manager = Agent(
    name="Memory Manager",
    model=Claude(id="claude-sonnet-4-5"),
    description=description,
    instructions=instructions,
    add_history_to_context=True,
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    num_history_runs=10,
    markdown=True,
    db=demo_db,
)
