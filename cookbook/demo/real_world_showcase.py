"""
Real-World Use Cases Showcase - Agno Framework

This demo showcases 10 innovative real-world applications built with Agno,
demonstrating the full range of capabilities including:
- Memory & Knowledge (RAG, user preferences, conversation history)
- Team Coordination (multi-agent workflows)
- Tool Integration (APIs, databases, web scraping)
- Structured Outputs (Pydantic schemas)
- Hooks & Validation (input/output validation)
- Async Operations & MCP Integration

Steps:
1. Run: `pip install agno yfinance duckduckgo-search newspaper4k lancedb openai` to install dependencies
2. Run: `python real_world_showcase.py` to launch AgentOS with all 10 use cases
3. Access the API at http://localhost:7780 or use the CLI

Author: Agno Team
"""

import asyncio
from pathlib import Path
from textwrap import dedent

from agno.os import AgentOS

# Import all single agents
from agents.agent_with_storage import travel_planner
from agents.agent_with_tools import personal_finance_agent
from agents.knowledge_agent import education_tutor, load_education_knowledge
from agents.structured_output_agent import ecommerce_recommender

# Import all teams
from teams.multi_agent_team import customer_support_team
from teams.team_with_knowledge import healthcare_team, load_medical_knowledge

# Import workflows
from workflows.content_creation_pipeline import content_creation_workflow

# ============================================================================
# Knowledge Base Initialization
# ============================================================================


async def initialize_knowledge_bases():
    """Initialize all knowledge bases with content"""
    await asyncio.gather(
        load_medical_knowledge(),
        load_education_knowledge(),
        return_exceptions=True,
    )


# ============================================================================
# AgentOS Configuration & Launch
# ============================================================================

# Create AgentOS instance with all use cases
agent_os = AgentOS(
    description=dedent("""\
        Real-World Use Cases Showcase - Agno Framework Demo

        This demo showcases core Agno framework capabilities through
        practical examples demonstrating:
        - Memory & Knowledge (RAG, user preferences, conversation history)
        - Team Coordination (multi-agent workflows)
        - Tool Integration (APIs, databases)
        - Structured Outputs (Pydantic schemas)
        - Hooks & Validation (input/output validation)
        - Storage & Persistence
    """),
    agents=[
        personal_finance_agent,  # Tools (YFinance)
        ecommerce_recommender,  # Structured Output
        education_tutor,  # Knowledge/RAG
        travel_planner,  # Storage
    ],
    teams=[
        customer_support_team,  # Multi-Agent
        healthcare_team,  # Team + Knowledge + Hooks
    ],
    workflows=[
        content_creation_workflow,  # Workflow Example
    ],
    config=str(Path(__file__).parent / "config.yaml"),
)

# Get the FastAPI app
app = agent_os.get_app()


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("🚀 Real-World Use Cases Showcase - Agno Framework")
    print("=" * 80)
    print("\nInitializing knowledge bases...")

    # Initialize knowledge bases
    asyncio.run(initialize_knowledge_bases())

    print("\n✅ All systems ready!")
    print("\n📋 Agno Framework Features Demonstrated:")
    print("\n   AGENTS (4):")
    print("   • Agent with Tools (YFinance) - Personal finance manager")
    print("   • Structured Output Agent - E-commerce recommender")
    print("   • Knowledge Agent (RAG) - Education tutor")
    print("   • Agent with Storage - Travel planner")
    print("\n   TEAMS (2):")
    print("   • Multi-Agent Team - Customer support workflow")
    print("   • Team with Knowledge + Hooks - Healthcare symptom checker")
    print("\n   WORKFLOWS (1):")
    print("   • Workflow Example - Content creation pipeline")

    print("\n🌐 Starting AgentOS on http://localhost:7780")
    print("=" * 80 + "\n")

    # Launch AgentOS
    agent_os.serve(app="real_world_showcase:app", host="localhost", port=7780, reload=True)
