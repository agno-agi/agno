from agno.agent import Agent
from agno.models.groq import Groq
from agno.tools.duckduckgo import DuckDuckGoTools

# Initialize the agent with the Groq model and tools for DuckDuckGo
agent = Agent(
    model=Groq(id="llama-3.3-70b-versatile"),
    description="You are an enthusiastic news reporter with a flair for storytelling!",
    tools=[DuckDuckGoTools()],  # Add DuckDuckGo tool to search the web
    show_tool_calls=True,  # Shows tool calls in the response, set to False to hide
    markdown=True,  # Format responses in markdown
)

# Prompt the agent to fetch a breaking news story from New York
agent.print_response("Tell me about a breaking news story from New York.", stream=True)
