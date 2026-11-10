"""
Sales Pipeline Forecaster
=========================

Read a deals spreadsheet, calculate weighted pipeline by stage, and forecast revenue.

Setup:
  1. Create a Google Sheet with columns: Deal Name, Company, Amount, Stage, Close Date, Probability
  2. Set SALES_PIPELINE_SHEET_ID env var to your spreadsheet ID
  3. Set Google OAuth credentials (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET)

Example Sheet Format:
  | Deal Name    | Company   | Amount  | Stage        | Close Date | Probability |
  |--------------|-----------|---------|--------------|------------|-------------|
  | Enterprise   | Acme Corp | 50000   | Negotiation  | 2026-07-15 | 70%         |
  | Starter Plan | Beta Inc  | 5000    | Discovery    | 2026-08-01 | 20%         |

Run:
  .venvs/demo/bin/python cookbook/91_tools/google/sheets/sales_pipeline.py
"""

from os import getenv

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.google.sheets import GoogleSheetsTools
from pydantic import BaseModel, Field


class PipelineForecast(BaseModel):
    total_pipeline: float = Field(..., description="Sum of all deal amounts")
    weighted_pipeline: float = Field(
        ..., description="Sum of amount * probability for each deal"
    )
    deals_by_stage: dict[str, int] = Field(..., description="Count of deals per stage")
    top_deals: list[str] = Field(..., description="Top 3 deals by weighted value")
    forecast_summary: str = Field(..., description="Brief forecast narrative")


agent = Agent(
    name="Pipeline Forecaster",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[GoogleSheetsTools(read_sheet=True)],
    instructions=[
        "You analyze sales pipeline data and provide revenue forecasts.",
        "Calculate weighted pipeline as: sum of (deal amount * probability) for each deal.",
        "Group deals by stage and identify the highest-value opportunities.",
        "Provide actionable insights about pipeline health.",
    ],
    output_schema=PipelineForecast,
    markdown=True,
)

if __name__ == "__main__":
    sheet_id = getenv("SALES_PIPELINE_SHEET_ID")
    if not sheet_id:
        print("Set SALES_PIPELINE_SHEET_ID to your spreadsheet ID")
        print(
            "Example: export SALES_PIPELINE_SHEET_ID=1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
        )
        exit(1)

    agent.print_response(
        f"Analyze the sales pipeline in spreadsheet {sheet_id} and provide a revenue forecast. "
        "Calculate the weighted pipeline value and identify our top opportunities.",
        stream=True,
    )
