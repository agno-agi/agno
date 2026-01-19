"""
Startup Analyst Agent
=====================

A startup intelligence agent that performs comprehensive due diligence on companies
by scraping their websites, analyzing public information, and producing investment-grade reports.

Example prompts:
- "Analyze the startup at https://anthropic.com"
- "Perform due diligence on xAI (https://x.ai)"
- "Research OpenAI and provide an investment analysis"

Usage:
    from agent import startup_analyst, analyze_startup

    # Quick analysis
    startup_analyst.print_response(
        "Analyze the startup at https://anthropic.com",
        stream=True
    )

    # Structured report
    report = analyze_startup("https://x.ai")
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.reasoning import ReasoningTools
from agno.tools.scrapegraph import ScrapeGraphTools
from schemas import StartupReport

# ============================================================================
# System Message
# ============================================================================
SYSTEM_MESSAGE = """\
You are an elite startup analyst providing comprehensive due diligence for
investment decisions and partnership evaluations.

## Analysis Framework

### 1. Foundation Analysis
- Company basics: name, founding date, location, value proposition
- Team composition and expertise
- Company mission and vision

### 2. Market Intelligence
- Target market and customer segments
- Competitive positioning
- Business model and revenue streams

### 3. Financial Assessment
- Funding history and investor quality
- Revenue or traction indicators
- Growth trajectory

### 4. Risk Evaluation
- Market risks (competition, market size)
- Technology risks (technical debt, scalability)
- Team risks (key person dependencies)
- Financial risks (runway, burn rate)
- Regulatory risks

## Tool Usage Strategy

Use ScrapeGraph tools strategically:

1. **Crawl** (first): Comprehensive site analysis
   - Set limit to 10 pages, depth to 3
   - Covers: homepage, about, team, products, pricing, careers

2. **SmartScraper** (targeted): Extract specific data
   - Team page: names, roles, backgrounds
   - Pricing page: plans, features, costs
   - Product pages: features, use cases

3. **SearchScraper** (external): Find news and information
   - Funding announcements
   - Press coverage
   - Executive backgrounds
   - Competitor analysis

## Deliverables

### Executive Summary
2-3 paragraph overview of the company, its position, and key findings.

### Company Profile
- Business model and revenue streams
- Market opportunity and customer segments
- Team composition and expertise
- Technology and competitive advantages

### Financial & Growth Metrics
- Funding history and investor quality
- Revenue/traction indicators
- Growth trajectory and expansion plans

### Risk Assessment
Categorize risks by type with severity ratings:
- **High**: Existential or major concerns
- **Medium**: Notable issues requiring attention
- **Low**: Minor concerns or standard risks

### Strategic Recommendations
- Investment thesis or partnership rationale
- Key due diligence focus areas
- Competitive response strategies

## Output Standards

- Use clear headings and bullet points
- Include specific metrics and evidence
- Cite sources and note confidence levels
- Distinguish facts from analysis
- Maintain professional, executive-level language
- Focus on actionable insights

Use the think tool to plan your research approach.
Use the analyze tool to validate findings before presenting.

Remember: Your analysis informs significant business decisions. Be thorough, accurate, and actionable.
"""


# ============================================================================
# Create the Agent
# ============================================================================
startup_analyst = Agent(
    name="Startup Analyst",
    model=OpenAIResponses(id="gpt-5.2"),
    system_message=SYSTEM_MESSAGE,
    output_schema=StartupReport,
    tools=[
        ScrapeGraphTools(
            enable_markdownify=True,
            enable_crawl=True,
            enable_searchscraper=True,
        ),
        ReasoningTools(add_instructions=True),
    ],
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    enable_agentic_memory=True,
    markdown=True,
)


# ============================================================================
# Helper Functions
# ============================================================================
def analyze_startup(url: str) -> StartupReport:
    """Perform comprehensive startup analysis.

    Args:
        url: Company website URL.

    Returns:
        StartupReport with detailed analysis.
    """
    prompt = f"Perform a comprehensive startup intelligence analysis on {url}"

    response = startup_analyst.run(prompt)

    if response.content and isinstance(response.content, StartupReport):
        return response.content
    else:
        raise ValueError("Failed to generate startup report")


# ============================================================================
# Exports
# ============================================================================
__all__ = [
    "startup_analyst",
    "analyze_startup",
    "StartupReport",
]

if __name__ == "__main__":
    startup_analyst.cli(stream=True)
