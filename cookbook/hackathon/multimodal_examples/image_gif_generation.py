from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.giphy import GiphyTools

gif_agent = Agent(
    name="Gif Generator Agent",
    agent_id="gif_agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GiphyTools()],
    description="You are an AI agent that can generate gifs using Giphy.",
    instructions=[
        "When the user asks you to create a gif, come up with the appropriate Giphy query and use the `search_gifs` tool to find the appropriate gif.",
        "Don't return the URL, only describe what you created.",
    ],
    markdown=True,
    debug_mode=True,
    add_history_to_messages=True,
    add_datetime_to_instructions=True,
)

gif_agent.run("Generate a gif of a cat playing with a toy")

for gif in gif_agent.run_response.images:
    print("Gif File URL:", gif.url)
