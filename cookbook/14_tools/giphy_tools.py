from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.giphy import GiphyTools

"""Create an agent specialized in creating gifs using Giphy """

# Example 1: Enable specific Giphy functions
gif_agent = Agent(
    name="Gif Generator Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GiphyTools(limit=5, enable_search_gifs=True)],
    description="You are an AI agent that can generate gifs using Giphy.",
    instructions=[
        "When the user asks you to create a gif, come up with the appropriate Giphy query and use the `search_gifs` tool to find the appropriate gif.",
    ],
)

# Example 2: Enable all Giphy functions
gif_agent_all = Agent(
    name="Full Giphy Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GiphyTools(limit=10, all=True)],
    description="You are an AI agent with full Giphy capabilities.",
    instructions=[
        "Use Giphy to find the perfect GIF for any situation or mood.",
        "Consider the user's context and preferences when searching.",
    ],
)

gif_agent.print_response("I want a gif to send to a friend for their birthday.")
