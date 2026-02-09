"""
Web Intelligence Agent - An agent that deeply analyzes websites and extracts intelligence.

This agent can:
- Analyze websites and extract structured information
- Gather competitive intelligence from company websites
- Extract product/pricing information
- Compare multiple websites
- Summarize web content and key facts

Example queries:
- "Analyze openai.com and summarize their product offerings"
- "Extract pricing information from anthropic.com"
- "Compare the websites of Stripe and Square"
- "What are the main products on tesla.com?"
"""

import sys
from pathlib import Path
from textwrap import dedent
from typing import List, Optional

from agno.agent import Agent
from agno.media import Image
from agno.models.openai import OpenAIResponses
from agno.tools import tool
from agno.tools.parallel import ParallelTools
from agno.tools.reasoning import ReasoningTools
from pydantic import BaseModel, Field
from db import demo_db


class WebAnalysis(BaseModel):
    company_name: str = Field(..., description="Company or website name")
    url: str = Field(..., description="Primary URL analyzed")
    summary: str = Field(..., description="One-paragraph overview of the company/website")
    products: List[str] = Field(..., description="Main products or services offered")
    target_audience: str = Field(..., description="Who they serve")
    key_differentiators: List[str] = Field(..., description="What makes them unique vs competitors")
    pricing_available: bool = Field(..., description="Whether pricing is publicly listed on the site")
    pricing_summary: Optional[str] = Field(None, description="Pricing overview if available")
    notable_findings: List[str] = Field(..., description="Interesting insights discovered")
    data_freshness: str = Field(..., description="When this data was gathered (date)")


@tool(requires_confirmation=True)
def save_analysis(company: str, analysis_json: str) -> str:
    """Save a competitive intelligence analysis to the workspace.

    Args:
        company: Company name for the filename.
        analysis_json: The analysis data to save as JSON.
    """
    workspace = Path(__file__).parent.parent / "workspace"
    workspace.mkdir(exist_ok=True)
    filepath = workspace / f"{company.lower().replace(' ', '_')}_analysis.json"
    filepath.write_text(analysis_json)
    return f"Analysis saved to {filepath}"


# ============================================================================
# Description & Instructions
# ============================================================================
description = dedent("""\
    You are the Web Intelligence Agent - an expert at analyzing websites, extracting
    structured information, and providing competitive intelligence.
    """)

instructions = dedent("""\
    You are an expert at gathering intelligence from websites. You can analyze any website
    and extract valuable structured information.

    CAPABILITIES:
    1. **Website Analysis** - Understand a website's purpose, structure, and content
    2. **Product Intelligence** - Extract product offerings, features, and positioning
    3. **Pricing Intelligence** - Find and structure pricing information
    4. **Competitive Analysis** - Compare multiple websites/companies
    5. **Content Extraction** - Pull key information and summarize

    TOOLS:
    - **ParallelTools (search)** - Search for information about websites/companies
    - **ParallelTools (extract)** - Extract content directly from web pages
    - **ReasoningTools** - Analyze and synthesize findings

    WORKFLOW:
    1. **Understand the Request**: What information does the user need?
    2. **Gather Data**: Use extract tool to pull content from target URLs
    3. **Supplement with Search**: Use search for additional context if needed
    4. **Analyze**: Structure and interpret the information
    5. **Present**: Deliver clear, actionable intelligence

    OUTPUT FORMAT:

    ## Website Analysis: [Company/Website]

    ### Overview
    - What the company/website does
    - Target audience
    - Key value proposition

    ### Products/Services
    | Product | Description | Key Features |
    |---------|-------------|--------------|
    | ...     | ...         | ...          |

    ### Pricing (if available)
    | Tier | Price | Includes |
    |------|-------|----------|
    | ...  | ...   | ...      |

    ### Key Differentiators
    - What makes this unique
    - Competitive advantages

    ### Notable Findings
    - Interesting insights
    - Recent updates/changes

    COMPARISON FORMAT (when comparing sites):

    ## Comparison: [Site A] vs [Site B]

    ### Overview
    | Aspect | Site A | Site B |
    |--------|--------|--------|
    | Focus  | ...    | ...    |
    | Target | ...    | ...    |

    ### Products
    (Comparison of offerings)

    ### Pricing
    (Comparison of pricing)

    ### Winner By Category
    - Best for X: [Site]
    - Best for Y: [Site]

    QUALITY STANDARDS:
    - Be specific with facts and figures
    - Note when information is not publicly available
    - Provide structured data where possible
    - Make comparisons clear and actionable
    - Acknowledge limitations (e.g., "pricing not public")
    """)

# ============================================================================
# Create the Agent
# ============================================================================
web_intelligence_agent = Agent(
    name="Web Intelligence Agent",
    role="Analyze websites and extract structured intelligence",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[
        ParallelTools(enable_search=True, enable_extract=True),
        ReasoningTools(add_instructions=True),
        save_analysis,
    ],
    output_schema=WebAnalysis,
    description=description,
    instructions=instructions,
    add_history_to_context=True,
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    markdown=True,
    db=demo_db,
)

# ============================================================================
# Demo Tests
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Web Intelligence Agent")
    print("   Website analysis and competitive intelligence")
    print("=" * 60)

    if len(sys.argv) > 1:
        message = " ".join(sys.argv[1:])
        web_intelligence_agent.print_response(message, stream=True)
    else:
        print("\n--- Demo 1: Structured Company Analysis ---")
        response = web_intelligence_agent.run(
            "Analyze anthropic.com - give me full competitive intelligence.",
        )
        if hasattr(response.content, "company_name"):
            print(f"Company: {response.content.company_name}")
            print(f"Products: {response.content.products}")
            print(f"Differentiators: {response.content.key_differentiators}")
        else:
            print(f"Response: {response.content}")

        print("\n--- Demo 2: Screenshot Analysis (multimodal) ---")
        sample_image = Path(__file__).parent.parent / "workspace" / "samples" / "sample_screenshot.png"
        if sample_image.exists():
            response = web_intelligence_agent.run(
                "Analyze this screenshot and extract key information about the company.",
                images=[Image(filepath=str(sample_image))],
            )
            if hasattr(response.content, "company_name"):
                print(f"Extracted company: {response.content.company_name}")
            else:
                print(f"Response: {response.content}")
        else:
            print("(Skipping - no sample image found)")

        print("\n--- Demo 3: Save Analysis (human-in-the-loop) ---")
        run_response = web_intelligence_agent.run("Analyze openai.com and save the analysis.")
        if run_response.active_requirements:
            for req in run_response.active_requirements:
                if req.needs_confirmation:
                    print(f"  Tool: {req.tool_execution.tool_name}")
                    print("  Auto-confirming for demo...")
                    req.confirm()
            run_response = web_intelligence_agent.continue_run(
                run_id=run_response.run_id,
                requirements=run_response.requirements,
            )
            print(f"  Result: {run_response.content}")
        else:
            print(f"  Response: {run_response.content}")
