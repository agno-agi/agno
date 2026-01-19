"""
Research Agent
==============

An autonomous research agent that investigates topics using Parallel's AI-optimized
web search, synthesizes findings from multiple sources, and produces comprehensive
research reports with citations.

Example prompts:
- "Research the current state of AI agents in production"
- "Compare vector databases for RAG applications"
- "What are the best practices for prompt engineering?"

Prerequisites:
    export PARALLEL_API_KEY=your-api-key

Usage:
    from agent import research_agent, research_topic

    # Quick research
    report = research_topic("What is RAG?", depth="quick")

    # Comprehensive research
    report = research_topic("Compare LangChain vs LlamaIndex", depth="comprehensive")
"""

from typing import Literal

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.parallel import ParallelTools
from agno.tools.reasoning import ReasoningTools
from schemas import ResearchReport

# ============================================================================
# Research Depth Configuration
# ============================================================================
DEPTH_CONFIG = {
    "quick": {
        "max_results": 5,
        "description": "Fast overview with 3-5 sources",
    },
    "standard": {
        "max_results": 10,
        "description": "Balanced research with 5-10 sources",
    },
    "comprehensive": {
        "max_results": 15,
        "description": "Thorough investigation with 10-15 sources",
    },
}


# ============================================================================
# System Message
# ============================================================================
SYSTEM_MESSAGE = """\
You are an expert research analyst. Your task is to investigate topics thoroughly
and produce well-structured research reports with proper citations.

## Your Responsibilities

1. **Understand the Question** - Clarify what information is needed
2. **Search Strategically** - Use both objectives and specific queries
3. **Evaluate Sources** - Assess credibility and relevance
4. **Synthesize Findings** - Combine information into coherent insights
5. **Cite Everything** - Every finding must have source attribution

## Research Process

### Step 1: Plan Your Research
Use the think tool to:
- Break down the research question into sub-topics
- Identify what types of sources would be authoritative
- Plan your search strategy (broad first, then specific)

### Step 2: Search with Parallel
Use `parallel_search` with:
- **objective**: Natural language description of what you're looking for
- **search_queries**: Specific keyword queries for targeted results

Example:
```
parallel_search(
    objective="Find best practices for building production AI agents",
    search_queries=["AI agent production best practices", "LLM agent deployment"]
)
```

### Step 3: Extract Deeper Content
When search results are promising but need more detail, use `parallel_extract`:
- Extract full content from the most relevant URLs
- Get clean markdown from JavaScript-heavy pages or PDFs

### Step 4: Evaluate and Synthesize
For each piece of information:
- Verify it appears in multiple sources when possible
- Note when sources disagree
- Assess source credibility:
  - **High**: Official docs, academic papers, established publications
  - **Medium**: Well-known blogs, industry sites, verified experts
  - **Low**: Personal blogs, forums, unverified sources

### Step 5: Identify Gaps
Note areas where:
- Information is contradictory
- Sources are limited or outdated
- More specialized research is needed

## Output Guidelines

### Executive Summary
- 2-3 sentences capturing the main answer
- Should stand alone without reading the full report

### Key Findings
- Each finding must cite at least one source URL
- Order by importance/relevance
- Include confidence level (high/medium/low)

### Methodology
- Briefly describe how research was conducted
- List the search approach used

### Recommendations
- Actionable next steps based on findings
- Suggestions for further research if needed

## Important Rules

1. NEVER fabricate sources or information
2. ALWAYS cite URLs for factual claims
3. Distinguish between facts and opinions
4. Note when information may be outdated
5. Be transparent about limitations

Use the think tool before searching to plan your approach.
Use the analyze tool after gathering results to evaluate what you've found.
"""


# ============================================================================
# Create the Agent
# ============================================================================
def create_research_agent(depth: str = "standard") -> Agent:
    """Create a research agent with the specified depth configuration.

    Args:
        depth: Research depth - "quick", "standard", or "comprehensive"

    Returns:
        Configured research agent
    """
    config = DEPTH_CONFIG.get(depth, DEPTH_CONFIG["standard"])

    return Agent(
        name="Research Agent",
        model=Claude(id="claude-sonnet-4-5"),
        system_message=SYSTEM_MESSAGE,
        output_schema=ResearchReport,
        tools=[
            ParallelTools(
                max_results=config["max_results"],
                enable_search=True,
                enable_extract=True,
            ),
            ReasoningTools(add_instructions=True),
        ],
        markdown=True,
    )


# Default agent with standard depth
research_agent = create_research_agent("standard")


# ============================================================================
# Helper Functions
# ============================================================================
def research_topic(
    question: str,
    depth: Literal["quick", "standard", "comprehensive"] = "standard",
) -> ResearchReport:
    """Research a topic and return a structured report.

    Args:
        question: The research question or topic to investigate.
        depth: Research depth - affects number of sources and thoroughness.
            - "quick": Fast overview, 3-5 sources
            - "standard": Balanced research, 5-10 sources
            - "comprehensive": Thorough investigation, 10-15 sources

    Returns:
        ResearchReport with findings, sources, and recommendations.
    """
    agent = create_research_agent(depth)
    config = DEPTH_CONFIG[depth]

    prompt = f"""Research the following topic and provide a {depth} report.

Research Question: {question}

Depth: {depth} ({config["description"]})

Please:
1. Use the think tool to plan your research strategy
2. Execute searches using parallel_search with both objective and specific queries
3. Extract content from the most promising sources if needed
4. Synthesize findings with proper citations
5. Identify any gaps or areas needing further research
"""

    response = agent.run(prompt)

    if response.content and isinstance(response.content, ResearchReport):
        return response.content
    else:
        raise ValueError("Failed to generate research report")


# ============================================================================
# Exports
# ============================================================================
__all__ = [
    "research_agent",
    "create_research_agent",
    "research_topic",
    "ResearchReport",
    "DEPTH_CONFIG",
]
