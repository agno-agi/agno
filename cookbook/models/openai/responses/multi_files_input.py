from agno.agent import Agent
from agno.media import File
from agno.models.openai import OpenAIResponses

agent = Agent(
    model=OpenAIResponses(id="gpt-4.1"),
    markdown=True,
    add_history_to_messages=True,
    debug_mode=True,
)

agent.print_response(
    "Analyze all the files and give me a summary of the content",
    files=[
        "data/car.json",
        File(filepath="data/boston_housing.csv"),
        File(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"),
    ],
)
