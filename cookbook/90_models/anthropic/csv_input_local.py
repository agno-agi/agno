from pathlib import Path

from agno.agent import Agent
from agno.media import File
from agno.models.anthropic import Claude

csv_path = Path(__file__).parent.joinpath("../../91_tools/imdb.csv")

agent = Agent(
    model=Claude(id="claude-sonnet-4-20250514"),
    markdown=True,
)

agent.print_response(
    "Analyze the top 10 highest-grossing movies in this dataset. Which genres perform best at the box office?",
    files=[
        File(
            filepath=csv_path,
            mime_type="text/csv",
        ),
    ],
)
