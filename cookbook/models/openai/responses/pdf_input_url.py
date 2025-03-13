from agno.agent import Agent
from agno.media import File
from agno.models.openai.responses import OpenAIResponses

agent = Agent(
    model=OpenAIResponses(id="gpt-4o-mini"),
    markdown=True,
)

agent.print_response(
    "Summarize the contents of the attached file.",
    files=[File(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf")],
)
