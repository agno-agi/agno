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
from agents.showcase.education_tutor import (
    education_tutor,
    load_education_knowledge,
)
from agents.showcase.ecommerce_product_recommender import ecommerce_recommender
from agents.showcase.legal_document_analyzer import (
    legal_analyzer,
    load_legal_knowledge,
)
from agents.showcase.personal_finance_manager import personal_finance_agent
from agents.showcase.travel_planning_assistant import travel_planner

# Import all teams
from teams.showcase.business_intelligence_team import bi_analyst_team
from teams.showcase.customer_support_team import customer_support_team
from teams.showcase.healthcare_symptom_checker_team import (
    healthcare_team,
    load_medical_knowledge,
)
from teams.showcase.hr_recruitment_team import hr_recruitment_team

# Import workflows
from workflows.showcase.content_creation_pipeline import content_creation_workflow

# ============================================================================
# Knowledge Base Initialization
# ============================================================================


async def initialize_knowledge_bases():
    """Initialize all knowledge bases with content"""
    await asyncio.gather(
        load_legal_knowledge(),
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
        Real-World Use Cases Showcase - 10 Innovative AI Applications

        This demo showcases the full capabilities of the Agno framework through
        practical, real-world use cases spanning customer support, content creation,
        finance, legal, HR, e-commerce, healthcare, business intelligence, education,
        and travel planning.

        Each use case demonstrates different Agno features:
        - Memory & Knowledge (RAG, user preferences, conversation history)
        - Team Coordination (multi-agent workflows)
        - Tool Integration (APIs, databases, web scraping)
        - Structured Outputs (Pydantic schemas)
        - Hooks & Validation (input/output validation)
        - Async Operations
    """),
    agents=[
        personal_finance_agent,
        legal_analyzer,
        ecommerce_recommender,
        education_tutor,
        travel_planner,
    ],
    teams=[
        customer_support_team,
        hr_recruitment_team,
        healthcare_team,
        bi_analyst_team,
    ],
    workflows=[
        content_creation_workflow,
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
    print("\n📋 Available Use Cases:")
    print("   1. Customer Support AI Team - Intelligent ticket classification & resolution")
    print("   2. Content Creation Pipeline - Automated research, writing & editing")
    print("   3. Personal Finance Manager - Investment analysis & financial advice")
    print("   4. Legal Document Analyzer - Contract review & legal research")
    print("   5. HR Recruitment Assistant - Resume screening & candidate evaluation")
    print("   6. E-commerce Product Recommender - Personalized shopping assistant")
    print("   7. Healthcare Symptom Checker - Educational health information")
    print("   8. Business Intelligence Team - Data analysis & strategic insights")
    print("   9. Education Tutor - Adaptive personalized learning")
    print("   10. Travel Planning Assistant - Comprehensive trip planning")

    print("\n🌐 Starting AgentOS on http://localhost:7780")
    print("=" * 80 + "\n")

    # Launch AgentOS
    agent_os.serve(app="real_world_showcase:app", host="localhost", port=7780, reload=True)
