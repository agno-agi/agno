# Parallel Tools

Web research and monitoring with [Parallel](https://parallel.ai).

## APIs

| API | Speed | Use Case |
|-----|-------|----------|
| **Search** | 1-5s | Quick lookups, gather sources |
| **Task** | 10s-25min | Deep research with structured output and citations |
| **Monitor** | Scheduled | Track topics over time, detect changes |

## Cookbooks

| File | API | Description |
|------|-----|-------------|
| `news_search.py` | Search | Fast web search for recent news |
| `output_schemas.py` | Task | All 4 output schema types |
| `company_enrichment.py` | Task | Enrich CRM records with web data |
| `market_research.py` | Task | Generate industry analysis reports |
| `investment_monitor.py` | Monitor | Track funding and M&A activity |
| `competitor_tracker.py` | Monitor | Watch competitor announcements |

## Setup

```bash
pip install parallel-web
export PARALLEL_API_KEY=<your-api-key>
```

## Quick Start

```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.parallel import ParallelTools

# Search API (default)
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[ParallelTools()],
)

# Task API
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[ParallelTools(enable_task=True)],
)

# Monitor API
agent = Agent(
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[ParallelTools(enable_monitor=True)],
)
```
