from datetime import datetime
from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.exa import ExaTools
from db import demo_db

research_agent = Agent(
    name="Research Agent",
    role="Assist with research and information synthesis",
    model=Claude(id="claude-sonnet-4-5"),
    tools=[
        ExaTools(
            start_published_date=datetime.now().strftime("%Y-%m-%d"),
            type="keyword",
        )
    ],
    description=dedent("""\
        You are the Research Agent — a research assistant that helps users explore any topic.
        You can search for up-to-date information, summarize key findings, and explain concepts clearly and accurately.
        """),
    instructions=dedent("""\
        1. Understand the user's query and identify the main research goal.
        2. Use ExaTools to run up to three targeted searches for relevant, recent information.
        3. Summarize and synthesize findings in a clear, conversational tone — avoid unnecessary jargon.
        4. Always prioritize credible sources and mention or link to them when appropriate.
        5. If the answer is already known or can be reasoned directly, respond concisely without searching.
        """),
    add_history_to_context=True,
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    markdown=True,
    db=demo_db,
)
