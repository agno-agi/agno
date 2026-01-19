# Startup Analyst

A startup intelligence agent that performs comprehensive due diligence on companies by scraping their websites, analyzing public information, and producing investment-grade reports.

## Quick Start

### 1. Prerequisites

```bash
# Set ScrapeGraph API key
export SGAI_API_KEY=your-scrapegraph-api-key

# Set OpenAI API key (for GPT-4o)
export OPENAI_API_KEY=your-openai-api-key
```

### 2. Run Examples

```bash
# Full startup analysis
.venvs/demo/bin/python cookbook/01_showcase/01_agents/startup_analyst/examples/analyze_startup.py

# Competitive intelligence
.venvs/demo/bin/python cookbook/01_showcase/01_agents/startup_analyst/examples/competitive_intel.py

# Quick scan
.venvs/demo/bin/python cookbook/01_showcase/01_agents/startup_analyst/examples/quick_scan.py
```

## Key Concepts

### Analysis Framework

The agent follows a structured due diligence process:

1. **Foundation Analysis**: Company basics, team, mission
2. **Market Intelligence**: Target market, competition, business model
3. **Financial Assessment**: Funding, revenue indicators, growth
4. **Risk Evaluation**: Market, technology, team, financial, regulatory risks

### ScrapeGraph Tools

The agent uses multiple scraping strategies:

| Tool | Use Case |
|------|----------|
| `crawl` | Comprehensive site analysis (10 pages, depth 3) |
| `smart_scraper` | Extract structured data from specific pages |
| `search_scraper` | Find external information (funding, news) |
| `markdownify` | Convert pages to clean markdown |

### Risk Categories

| Category | Examples |
|----------|----------|
| Market | Competition, market size, timing |
| Technology | Technical debt, scalability, dependencies |
| Team | Key person risk, expertise gaps |
| Financial | Runway, burn rate, funding environment |
| Regulatory | Compliance, legal, policy changes |

## Output Structure

```python
from schemas import StartupReport

report = StartupReport(
    company_name="Example Corp",
    website="https://example.com",
    value_proposition="...",
    business_model="...",
    funding_history=[FundingRound(...)],
    risks=[RiskAssessment(...)],
    investment_thesis="...",
    confidence_score=0.85,
    executive_summary="..."
)
```

## Architecture

```
Company URL
    |
    v
[Startup Analyst (GPT-5.2)]
    |
    +---> ScrapeGraphTools
    |         |
    |         +---> Crawl (site overview)
    |         +---> SmartScraper (targeted extraction)
    |         +---> SearchScraper (external info)
    |
    +---> ReasoningTools ---> Think/Analyze
    |
    v
StartupReport (Structured Output)
```

## Dependencies

- `agno` - Core framework
- `openai` - GPT-5.2 model
- `scrapegraph-py` - Web scraping API

## API Credentials

To use this agent, you need a ScrapeGraph API key:

1. Go to [scrapegraph.ai](https://scrapegraph.ai)
2. Create an account
3. Get your API key
4. Set `SGAI_API_KEY` environment variable
