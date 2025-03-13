"""Please install dependencies using:
pip install openai duckduckgo-search newspaper4k lxml_html_clean agno
"""

from agno.agent import Agent
from agno.models.huggingface import HuggingFace
from agno.tools.duckduckgo import DuckDuckGoTools

agent = Agent(
    model=HuggingFace(id="Qwen/Qwen2.5-Coder-32B-Instruct"),
    tools=[DuckDuckGoTools()],
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
agent.print_response("Simulation theory")
