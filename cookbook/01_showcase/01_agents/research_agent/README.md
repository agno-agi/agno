# Research Agent

An autonomous research agent that investigates topics using Parallel's AI-optimized web search, synthesizes findings from multiple sources, and produces comprehensive research reports with citations.

## What You'll Learn

| Concept | Description |
|:--------|:------------|
| **Web Search** | Using Parallel's AI-optimized search API |
| **Content Extraction** | Extracting clean content from any URL |
| **Source Evaluation** | Assessing credibility of sources |
| **Multi-Source Synthesis** | Combining findings with citations |

## Quick Start

### 1. Install Dependencies

```bash
pip install parallel-web
```

### 2. Set API Key

```bash
export PARALLEL_API_KEY=your-api-key
```

### 3. Run an Example

```bash
.venvs/demo/bin/python cookbook/01_showcase/01_agents/research_agent/examples/quick_research.py
```

## Examples

| File | What You'll Learn |
|:-----|:------------------|
| `examples/quick_research.py` | Fast overview research (3-5 sources) |
| `examples/deep_research.py` | Comprehensive investigation (10-15 sources) |
| `examples/comparative.py` | Comparison and decision support |
| `examples/evaluate.py` | Automated accuracy testing |

## Architecture

```
research_agent/
├── agent.py          # Main agent with Parallel tools
├── schemas.py        # Pydantic models for reports
└── examples/
```

## Key Concepts

### Research Depth

The agent supports three depth levels:

| Depth | Sources | Use Case |
|:------|:--------|:---------|
| `quick` | 3-5 | Fast answers, basic understanding |
| `standard` | 5-10 | Balanced research for most tasks |
| `comprehensive` | 10-15 | Thorough investigation, decision support |

### Using Parallel Tools

The agent uses two Parallel APIs:

**Search API** - AI-optimized web search:
```python
parallel_search(
    objective="Find best practices for AI agents",
    search_queries=["AI agent best practices", "LLM agent production"]
)
```

**Extract API** - Clean content from URLs:
```python
parallel_extract(
    urls=["https://example.com/article"],
    objective="Extract information about deployment"
)
```

### Research Report Schema

```python
class ResearchReport(BaseModel):
    question: str           # Original question
    executive_summary: str  # 2-3 sentence overview
    key_findings: list[Finding]  # Main discoveries with sources
    methodology: str        # How research was conducted
    sources: list[Source]   # All sources with credibility ratings
    gaps: list[str]         # Areas needing more research
    recommendations: list[str]  # Suggested next steps
    research_depth: str     # quick, standard, comprehensive
```

### Source Credibility

Sources are evaluated as:
- **High**: Official docs, academic papers, established publications
- **Medium**: Industry blogs, verified experts, known tech sites
- **Low**: Personal blogs, forums, unverified sources

## Usage Patterns

### Quick Research

```python
from research_agent import research_topic

report = research_topic("What is RAG?", depth="quick")
print(report.executive_summary)
```

### Comprehensive Research

```python
report = research_topic(
    "Best practices for building production AI agents",
    depth="comprehensive"
)

for finding in report.key_findings:
    print(f"- {finding.statement}")
    print(f"  Sources: {finding.sources}")
```

### Using the Agent Directly

```python
from research_agent import research_agent

research_agent.print_response(
    "Research: What are the latest trends in AI agents?",
    stream=True
)
```

### Custom Depth Configuration

```python
from research_agent import create_research_agent

# Create agent with specific configuration
agent = create_research_agent(depth="comprehensive")
response = agent.run("Research: Compare vector databases")
```

## Requirements

- Python 3.11+
- Parallel API key
- OpenAI API key

## Environment Variables

```bash
export PARALLEL_API_KEY=your-parallel-key
export OPENAI_API_KEY=your-openai-key
```

## Why Parallel?

| Feature | Benefit |
|:--------|:--------|
| **Objective-based search** | Natural language search goals |
| **AI-tailored excerpts** | Relevant passages, not just links |
| **Content extraction** | Clean markdown from any URL |
| **JS/PDF handling** | Works with modern web pages |
