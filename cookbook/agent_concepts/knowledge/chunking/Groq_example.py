from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.newspaper4k import Newspaper4kTools

agent = Agent(
    model=OpenAIChat(id="gpt-4.1-nano"),
    tools=[DuckDuckGoTools(), Newspaper4kTools()],
    description="You are a senior Physician specialised in Infectious Disease writing an article on a topic.",
    instructions=[
        "For a given topic, search for the top 5 links.",
        "Then read each URL and extract the article text, if a URL isn't available, ignore it.",
        "Analyse and prepare an Nature worthy article based on the information.",
        "Write two paragrafs about the topic."
    ],
    markdown=True,
    show_tool_calls=True,
    add_datetime_to_instructions=True,
)
agent.print_response("MPox and HIV", stream=True)