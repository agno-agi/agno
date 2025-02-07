"""Please install dependencies using:
pip install openai duckduckgo-search newspaper4k lxml_html_clean agno
"""

import asyncio

from agno.agent import Agent
from agno.models.groq import Groq
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.newspaper4k import Newspaper4kTools

agent = Agent(
    model=Groq(id="llama-3.3-70b-versatile"),
    tools=[DuckDuckGoTools(), Newspaper4kTools()],
    description="You are a senior NYT researcher writing an article on a topic.",
    instructions=[
        "For a given topic, search for the top 5 links.",
        "Then read each URL and extract the article text, if a URL isn't available, ignore it.",
        "Analyse and prepare an NYT worthy article based on the information.",
    ],
    markdown=True,
    show_tool_calls=True,
    add_datetime_to_instructions=True,
)

# -*- Print a response to the cli
asyncio.run(agent.aprint_response("Simulation theory", stream=True))
