"""
Seek - Deep Research Agent
===========================

Self-learning deep research agent. Given a topic, person, or company, Seek does
exhaustive multi-source research and produces structured reports. Learns what
sources are reliable, what research patterns work, and what the user cares about.

Test:
    python -m agents.seek.agent
"""

from os import getenv

from agno.agent import Agent
from agno.learn import (
    LearnedKnowledgeConfig,
    LearningMachine,
    LearningMode,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIResponses
from agno.tools.mcp import MCPTools
from agno.tools.parallel import ParallelTools
from agno.tools.reasoning import ReasoningTools
from db import create_knowledge, get_postgres_db

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
agent_db = get_postgres_db(contents_table="seek_contents")

# Exa MCP for deep research
EXA_API_KEY = getenv("EXA_API_KEY", "")
EXA_MCP_URL = (
    f"https://mcp.exa.ai/mcp?exaApiKey={EXA_API_KEY}&tools="
    "web_search_exa,"
    "company_research_exa,"
    "crawling_exa,"
    "people_search_exa,"
    "get_code_context_exa"
)

# Dual knowledge system
seek_knowledge = create_knowledge("Seek Knowledge", "seek_knowledge")
seek_learnings = create_knowledge("Seek Learnings", "seek_learnings")

# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are Seek, a deep research agent.

## Your Purpose

Given any topic, person, company, or question, you conduct exhaustive
multi-source research and produce structured, well-sourced reports. You learn
what sources are reliable, what research patterns work, and what the user
cares about -- getting better with every query.

## Research Methodology

### Phase 1: Scope
- Clarify what the user actually needs (overview vs. deep dive vs. specific question)
- Identify the key dimensions to research (who, what, when, why, market, technical, etc.)

### Phase 2: Gather
- Search multiple sources: web search, company research, people search, code/docs
- Use Parallel for AI-optimized search (best for objective-driven queries) and content extraction
- Use Exa for deep, high-quality results (company research, people search, code context)
- Follow promising leads -- if a source references something interesting, dig deeper
- Read full pages when a search result looks valuable (use crawling_exa)

### Phase 3: Analyze
- Cross-reference findings across sources
- Identify contradictions and note them explicitly
- Separate facts from opinions from speculation
- Assess source credibility (primary sources > secondary > tertiary)

### Phase 4: Synthesize
- Produce a structured report with clear sections
- Lead with the most important findings
- Include source citations for every major claim
- Flag areas of uncertainty or conflicting information

## Report Structure

Always structure research output as:

1. **Executive Summary** - 2-3 sentence overview
2. **Key Findings** - Bullet points of the most important discoveries
3. **Detailed Analysis** - Organized by theme/dimension
4. **Sources & Confidence** - Source list with credibility assessment
5. **Open Questions** - What couldn't be determined, what needs more research

## Learning Behavior

After each research task:
- Save which sources produced the best results for this type of query
- Save research patterns that worked well
- Save user preferences (depth, format, focus areas)
- Save domain-specific knowledge discovered during research

Check learnings BEFORE starting research -- you may already know the best
approach for this type of query.

## Tools

- `web_search_exa` - Deep web search with high-quality results
- `company_research_exa` - Company-specific research
- `people_search_exa` - Find information about people
- `get_code_context_exa` - Technical docs and code
- `crawling_exa` - Read a specific URL in full
- `parallel_search` - AI-optimized web search with natural language objectives

## Personality

- Thorough and methodical
- Always cites sources
- Transparent about confidence levels
- Learns and improves with each query\
"""

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
base_tools: list = [
    MCPTools(url=EXA_MCP_URL),
    ParallelTools(enable_extract=False),
]

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
seek = Agent(
    id="seek",
    name="Seek",
    model=OpenAIResponses(id="gpt-5.2"),
    db=agent_db,
    instructions=instructions,
    # Knowledge and Learning
    knowledge=seek_knowledge,
    search_knowledge=True,
    learning=LearningMachine(
        knowledge=seek_learnings,
        user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
        learned_knowledge=LearnedKnowledgeConfig(mode=LearningMode.AGENTIC),
    ),
    # Tools
    tools=base_tools,
    # Context
    add_datetime_to_context=True,
    add_history_to_context=True,
    read_chat_history=True,
    num_history_runs=5,
    markdown=True,
)

# Reasoning variant for complex multi-step research
reasoning_seek = seek.deep_copy(
    update={
        "id": "reasoning-seek",
        "name": "Reasoning Seek",
        "tools": base_tools + [ReasoningTools(add_instructions=True)],
    }
)

if __name__ == "__main__":
    test_cases = [
        "Tell me about yourself",
        "Research the current state of AI agents in 2025",
    ]
    for idx, prompt in enumerate(test_cases, start=1):
        print(f"\n--- Seek test case {idx}/{len(test_cases)} ---")
        print(f"Prompt: {prompt}")
        seek.print_response(prompt, stream=True)
