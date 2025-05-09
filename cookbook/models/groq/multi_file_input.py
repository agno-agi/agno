from agno.agent import Agent
from agno.media import File
from agno.models.groq import Groq

agent = Agent(
    model=Groq(id="meta-llama/llama-4-maverick-17b-128e-instruct"),
    markdown=True,
    add_history_to_messages=True,
)

agent.print_response(
    "Analyze all the files and give me a summary of the content",
    files=[
        File(filepath="data/car.json"),
        File(filepath="data/boston_housing.csv"),
        File(filepath="data/LSTM.pdf"),
        "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        "https://api.fda.gov/food/enforcement.json",
    ],
)
