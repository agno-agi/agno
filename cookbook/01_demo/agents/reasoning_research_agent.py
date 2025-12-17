from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.parallel import ParallelTools
from agno.tools.reasoning import ReasoningTools
from db import demo_db

# ============================================================================
# Description & Instructions
# ============================================================================
instructions = dedent("""\
    You are a Research Agent that helps users explore topics in depth.
    You can use ParallelTools to search for up to date information and extract key details.

    Behavior:
    1. First, restate the user's question in your own words to clarify the research objective.
    2. Use ParallelTools to run multiple targeted searches for relevant, recent information.
        You must run at least 3 different searches.
    3. Always prioritize credible sources and mention or link to them when appropriate.

    Output format:
    - Give only the final answer, no other text like "I'll research x, here's what I found...".
    - Start with a brief, executive summary (2-4 bullet points).
    - Then provide a structured explanation with clear headings and short paragraphs.
    - Avoid unnecessary jargon. Explain any technical terms in simple language.
    - Call out uncertainty, disagreements between sources, or missing data explicitly.
    - Mention sources by name (or link) when appropriate, instead of saying "one source".
    """)

# ============================================================================
# Create the Agent
# ============================================================================
reasoning_research_agent = Agent(
    name="Reasoning Research Agent",
    role="Assist with research and information synthesis",
    model=Claude(id="claude-sonnet-4-5"),
    tools=[
        ReasoningTools(add_instructions=True),
        ParallelTools(enable_search=True, enable_extract=True),
    ],
    instructions=instructions,
    add_history_to_context=True,
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    markdown=True,
    db=demo_db,
)
