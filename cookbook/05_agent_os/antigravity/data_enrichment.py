"""
Data Enrichment with Antigravity on AgentOS
============================================

Give the agent a list of partial records (just company names) and let
Antigravity browse the web to fill in the missing fields. The response is
parsed into a Pydantic model so the enriched data is ready to drop into a
spreadsheet, database, or downstream pipeline.

Antigravity runs in a managed sandbox, so it can plan, browse, and
cross-reference sources without any tools wired up by us - the model finds
the data itself.

Run:
    python cookbook/05_agent_os/antigravity/data_enrichment.py

Then either hit the AgentOS UI / API on http://localhost:7777, or run the
__main__ demo below by setting RUN_DEMO=1.
"""

import os
from typing import List, Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import GeminiInteractions
from agno.os import AgentOS
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class EnrichedCompany(BaseModel):
    name: str = Field(description="Canonical company name")
    website: Optional[str] = Field(default=None, description="Primary website URL")
    founded_year: Optional[int] = Field(
        default=None, description="Year the company was founded"
    )
    headquarters: Optional[str] = Field(
        default=None, description="City, Country of the headquarters"
    )
    industry: Optional[str] = Field(
        default=None, description="Primary industry or sector"
    )
    employees: Optional[str] = Field(
        default=None,
        description="Approximate employee count as a string (e.g. '1,000-5,000' or '~12k')",
    )
    ceo: Optional[str] = Field(default=None, description="Current CEO")
    one_liner: Optional[str] = Field(
        default=None, description="One sentence description of what the company does"
    )
    sources: List[str] = Field(
        default_factory=list, description="URLs the agent used to ground the answer"
    )


class EnrichmentResult(BaseModel):
    companies: List[EnrichedCompany] = Field(
        description="Enriched records, one per input company"
    )


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/antigravity_data_enrichment.db")

# ---------------------------------------------------------------------------
# Create the Data Enrichment Agent
# ---------------------------------------------------------------------------
data_enrichment_agent = Agent(
    id="data-enrichment-agent",
    name="Data Enrichment Agent",
    db=db,
    model=GeminiInteractions(
        agent="antigravity-preview-05-2026",
        environment="remote",
    ),
    description=(
        "Researches a list of companies (or other entities) and returns a "
        "structured, fully populated record for each one."
    ),
    instructions=[
        "You enrich partial records by searching the web for authoritative data.",
        "For each input company, find: website, founded year, headquarters, industry, "
        "employee count, current CEO, and a one-sentence description.",
        "Prefer primary sources (the company's own site, SEC filings, official press releases) "
        "over aggregators when they disagree.",
        "If a field cannot be verified from at least one credible source, leave it null - "
        "do NOT guess.",
        "Always include the URLs you actually used in the `sources` list for each record.",
        "Return one record per input company, in the same order as the input.",
    ],
    output_schema=EnrichmentResult,
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS App
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    description="Antigravity-powered data enrichment service",
    agents=[data_enrichment_agent],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
def _format_input(companies: List[str]) -> str:
    bullets = "\n".join(f"- {c}" for c in companies)
    return (
        "Enrich the following companies. Search the web for the latest data, "
        "verify against primary sources, and return one structured record per "
        "company.\n\nCompanies:\n" + bullets
    )


if __name__ == "__main__":
    if os.getenv("RUN_DEMO") == "1":
        sample_companies = ["Agno", "Anthropic", "Hugging Face"]
        response = data_enrichment_agent.run(_format_input(sample_companies))

        result = response.content
        if isinstance(result, EnrichmentResult):
            for record in result.companies:
                print("\n" + "=" * 60)
                print(record.name)
                print("=" * 60)
                print("Website:      ", record.website)
                print("Founded:      ", record.founded_year)
                print("HQ:           ", record.headquarters)
                print("Industry:     ", record.industry)
                print("Employees:    ", record.employees)
                print("CEO:          ", record.ceo)
                print("Summary:      ", record.one_liner)
                if record.sources:
                    print("Sources:")
                    for url in record.sources:
                        print("  -", url)
        else:
            print("Unexpected response:", result)
    else:
        agent_os.serve(app="data_enrichment:app", reload=True)
