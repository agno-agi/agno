from agno.agent import Agent
from agno.media import File
from agno.models.openai.responses import OpenAIResponses

agent = Agent(
    model=OpenAIResponses(id="gpt-4o-mini"),
    tools=[{"type": "file_search"}, {"type": "web_search_preview"}],
    markdown=True,
)

agent.print_response(
    "Summarize the contents of the attached file and search the web for more information.",
    files=[File(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf")],
)

print("Citations:")
print(agent.run_response.citations)
