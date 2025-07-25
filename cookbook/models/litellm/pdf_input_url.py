from agno.agent import Agent
from agno.media import File
from agno.models.litellm import LiteLLM

agent = Agent(
    model=LiteLLM(id="openai/gpt-4o"),
    markdown=True,
    add_history_to_messages=True,
)

agent.print_response(
    "What type of document is this and what's it about? Give me a detailed summary.",
    files=[File(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf")],
)
