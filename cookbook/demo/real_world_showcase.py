"""
Real-World Use Cases Showcase - Agno Framework

This demo showcases 3 comprehensive agents built with Agno,
demonstrating the full range of capabilities including:
- Memory & Knowledge (RAG, user preferences, conversation history)
- Tool Integration (APIs, databases, web scraping)
- Structured Outputs (Pydantic schemas)
- Hooks & Validation (input/output validation)
- Agent State Management
- Automatic Metrics Display

Steps:
1. Run: `pip install agno yfinance duckduckgo-search lancedb openai` to install dependencies
2. Run: `python real_world_showcase.py` to launch AgentOS with all agents
3. Access the API at http://localhost:7780 or use the CLI

Author: Agno Team
"""

import asyncio
from os import getenv
from pathlib import Path
from textwrap import dedent

from agents.creative_studio import creative_studio
from agents.lifestyle_concierge import lifestyle_concierge

# Import consolidated agents
from agents.study_buddy import load_education_knowledge, study_buddy
from agno.os import AgentOS

# ============================================================================
# Knowledge Base Initialization
# ============================================================================
teams_list = []
github_token = getenv("GITHUB_ACCESS_TOKEN") or getenv("GITHUB_TOKEN")
if github_token:
    from teams.oss_maintainer_team import oss_maintainer_team

    teams_list.append(oss_maintainer_team)


async def initialize_knowledge_bases():
    """Initialize all knowledge bases with content"""
    await asyncio.gather(
        load_education_knowledge(),  # Study Buddy agent
        return_exceptions=True,
    )


# ============================================================================
# AgentOS Configuration & Launch
# ============================================================================

# Create AgentOS instance with all agents
agent_os = AgentOS(
    description=dedent("""\
        Real-World Use Cases Showcase - Agno Framework Demo
        AGENTS (3):
        • Lifestyle Concierge - Multi-domain (finance/shopping/travel) with tools,
          structured outputs, guardrails, memory, storage, and agent state
        • Study Buddy - RAG/vector search with input validation hooks,
          tool monitoring, and multi-source knowledge retrieval
        • Creative Studio - Multimodal (image generation/analysis) with
          tool hooks and comprehensive guardrails
    """),
    agents=[
        lifestyle_concierge,  # Multi-domain: Tools + Structured Outputs + Guardrails + Memory + Storage + Agent State
        study_buddy,  # Study Buddy: RAG + Input Validation + Tool Hooks + Memory
        creative_studio,  # Creative Studio: Multimodal + Tool Hooks + Guardrails
    ],
    teams=teams_list,
    config=str(Path(__file__).parent / "showcase_config.yaml"),
)

# Get the FastAPI app
app = agent_os.get_app()


if __name__ == "__main__":
    print("\nInitializing knowledge bases...")
    # Initialize knowledge bases
    asyncio.run(initialize_knowledge_bases())
    # Launch AgentOS
    agent_os.serve(
        app="real_world_showcase:app", host="localhost", port=7780, reload=True
    )
