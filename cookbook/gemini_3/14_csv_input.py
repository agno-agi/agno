"""
CSV Input - Analyze Datasets Directly
=======================================
Pass CSV files to Gemini for analysis. No pandas or data processing needed.

Key concepts:
- File(filepath=..., mime_type="text/csv"): Pass a local CSV file
- download_file: Utility to download remote files to local workspace
- Native capability: No pandas or data processing libraries needed
- Data analysis: The model can compute statistics, find trends, and create summaries

Example prompts to try:
- "Analyze the top 10 highest-grossing movies in this dataset"
- "What genres have the highest average ratings?"
- "Find any interesting trends or outliers in this data"
"""

from pathlib import Path

from agno.agent import Agent
from agno.media import File
from agno.models.google import Gemini
from agno.utils.media import download_file

WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a data analyst. Analyze datasets and provide clear insights
with tables and summaries.

## Rules

- Start with an overview of the dataset (rows, columns, types)
- Use tables for comparisons and rankings
- Highlight interesting patterns or outliers
- Be specific with numbers\
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
csv_agent = Agent(
    name="Data Analyst",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    csv_path = WORKSPACE / "IMDB-Movie-Data.csv"

    # Download sample dataset if not already present
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

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
CSV analysis patterns:

1. Quick overview
   "Describe this dataset: columns, row count, data types"

2. Rankings and comparisons
   "What are the top 10 items by revenue?"

3. Trend analysis
   "How have ratings changed over the years?"

4. With structured output
   class DataSummary(BaseModel):
       total_rows: int
       top_items: List[str]
       average_rating: float
       trend: str

   agent = Agent(model=Gemini(...), output_schema=DataSummary)
   result = agent.run("Summarize this data", files=[...])

Use cases for music/film/gaming:
- Analyze streaming metrics for music catalog
- Review box office performance data for films
- Process player engagement data for games
"""
