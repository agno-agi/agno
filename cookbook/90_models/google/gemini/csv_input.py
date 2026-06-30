"""
Google Csv Input
================

Cookbook example for `google/gemini/csv_input.py`.
"""

from pathlib import Path

from agno.agent import Agent
from agno.media import File
from agno.models.google import Gemini
from agno.utils.media import download_file

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

csv_path = Path(__file__).parent.joinpath("IMDB-Movie-Data.csv")

download_file(
    "https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv", str(csv_path)
)

agent = Agent(
    model=Gemini(id="gemini-2.5-flash"),
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

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pass
