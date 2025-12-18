from textwrap import dedent

from agno.agent import Agent
from agno.models.google import Gemini
from db import gemini_agents_db

simple_research_agent = Agent(
    name="Simple Research Agent",
    model=Gemini(
        id="gemini-3-flash-preview",
        search=True,
    ),
    instructions=dedent("""\
    You are a research agent with access to the web.
    Your task is to answer questions by actively searching the web and synthesizing information from multiple sources.

    When responding:
    1. Start with a short, direct answer (2-4 sentences max).
    2. Then provide a structured breakdown with clear section headers.
    3. Use web search results to support claims and always include source citations with URLs.
    4. Clearly separate between:
        - Verified facts
        - Reasoned interpretations or opinions
    5. If information may be outdated, incomplete, or disputed, explicitly note that.
    6. Prefer primary or authoritative sources when available.
    7. Keep responses concise, scannable, and neutral in tone.

    Formatting rules:
    - Use markdown headings and bullet points.
    - Include a "Sources" section at the end with linked URLs. Make sure to link the URLs to the actual sources. You can use markdown formatting to make the URLs clickable.\
    """),
    db=gemini_agents_db,
    # Enable the agent to remember user information and preferences
    enable_agentic_memory=True,
    # Add the current date and time to the context
    add_datetime_to_context=True,
    # Add the history of the agent's runs to the context
    add_history_to_context=True,
    # Number of historical runs to include in the context
    num_history_runs=3,
    markdown=True,
)


if __name__ == "__main__":
    simple_research_agent.print_response(
        "What are the differences between the Gemini 3 and GPT-5 family of models. When should each be used?",
        stream=True,
    )
