from agno.agent import Agent
from agno.media import File
from agno.models.google import Gemini

agent = Agent(
    model=Gemini(id="gemini-2.0-flash"),
    markdown=True,
    add_history_to_messages=True,
)

agent.print_response(
    "Analyze all the files and give me a summary of the content",
    files=[
        File(filepath="data/car.json"),
        File(filepath="data/boston_housing.csv"),
        File(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"),
        "https://api.fda.gov/food/enforcement.json",
        "https://www.jsu.edu/business/fea/docs/financial_stament_review.pdf",
    ],
)
