from textwrap import dedent

from agno.agent import Agent
from agno.models.google import Gemini
from db import demo_db

research_agent = Agent(
    name="Research Agent",
    model=Gemini(
        id="gemini-3-pro-preview",
        search=True,
    ),
    description="You are a research agent with access to the web. You can search the web and provide well-researched responses.",
    instructions=dedent("""\
1. Search the web and provide well-researched responses.

2. With every response, you must: 
    - Include source citations with URLs when available.
    - Distinguish facts from opinions.  
    - Note if information may be outdated.

3. Start with a concise answer, then provide supporting details.

4. Keep responses focused and scannable with clear headings.
        """),
    db=demo_db,
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)


if __name__ == "__main__":
    research_agent.print_response(
        "What are the latest breakthroughs in quantum computing this year?",
        stream=True,
    )
