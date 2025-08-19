from agno.agent import Agent
from agno.tools.confluence import ConfluenceTools

agent = Agent(
    name="Confluence agent",
    tools=[ConfluenceTools()],
    markdown=True,
)

## getting space details
agent.print_response("How many spaces are there and what are their names?")

## getting page_content
agent.print_response(
    "What is the content present in page 'Large language model in LLM space'"
)

## getting page details in a particular space
agent.print_response("Can you extract all the page names from 'LLM' space")

## creating a new page in a space
agent.print_response("Can you create a new page named 'TESTING' in 'LLM' space")
