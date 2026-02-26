"""
14. CSV Input
=============
Gemini can analyze CSV files directly -- no need to parse them yourself.
Pass CSV files with mime_type="text/csv".

Run:
    python cookbook/gemini_3/14_csv_input.py

Example prompt:
    "Analyze the top 10 highest-grossing movies in this dataset."
"""

from pathlib import Path

from agno.agent import Agent
from agno.media import File
from agno.models.google import Gemini
from agno.utils.media import download_file

# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
csv_agent = Agent(
    name="Data Analyst",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions="You are a data analyst. Analyze datasets and provide clear insights with tables and summaries.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    csv_path = WORKSPACE / "IMDB-Movie-Data.csv"

    download_file(
        "https://agno-public.s3.amazonaws.com/demo_data/IMDB-Movie-Data.csv",
        str(csv_path),
    )

    csv_agent.print_response(
        "Analyze the top 10 highest-grossing movies in this dataset. "
        "Which genres perform best at the box office?",
        files=[
            File(filepath=csv_path, mime_type="text/csv"),
        ],
        stream=True,
    )
