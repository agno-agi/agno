from agno.agent import Agent
from agno.media import File
from agno.models.openai import OpenAIChat

agent = Agent(
    model=OpenAIChat(id="gpt-4.1"),
    markdown=True,
    add_history_to_messages=True,
)

agent.print_response(
    "Use the attached file to answer questions. Only refer to the file",
    files=[File(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf")],
)

agent.print_response("Suggest me a recipe from the attached file.")
