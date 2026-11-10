"""
Condition With List
===================

Demonstrates condition branches that execute a list of multiple steps, including parallel conditional blocks.
"""

import asyncio

from agno.agent.agent import Agent
from agno.tools.exa import ExaTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.condition import Condition
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
hackernews_agent = Agent(
    name="HackerNews Researcher",
    instructions="Research tech news and trends from Hacker News",
    tools=[HackerNewsTools()],
)

exa_agent = Agent(
    name="Exa Search Researcher",
    instructions="Research using Exa advanced search capabilities",
    tools=[ExaTools()],
)

content_agent = Agent(
    name="Content Creator",
    instructions="Create well-structured content from research data",
)

trend_analyzer_agent = Agent(
    name="Trend Analyzer",
    instructions="Analyze trends and patterns from research data",
)

fact_checker_agent = Agent(
    name="Fact Checker",
    instructions="Verify facts and cross-reference information",
)

# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
research_hackernews_step = Step(
    name="ResearchHackerNews",
    description="Research tech news from Hacker News",
    agent=hackernews_agent,
)

research_exa_step = Step(
    name="ResearchExa",
    description="Research using Exa search",
    agent=exa_agent,
)

deep_exa_analysis_step = Step(
    name="DeepExaAnalysis",
    description="Conduct deep analysis using Exa search capabilities",
    agent=exa_agent,
)

trend_analysis_step = Step(
    name="TrendAnalysis",
    description="Analyze trends and patterns from the research data",
    agent=trend_analyzer_agent,
)

fact_verification_step = Step(
    name="FactVerification",
    description="Verify facts and cross-reference information",
    agent=fact_checker_agent,
)

write_step = Step(
    name="WriteContent",
    description="Write the final content based on research",
    agent=content_agent,
)


# ---------------------------------------------------------------------------
# Define Condition Evaluators
# ---------------------------------------------------------------------------
def check_if_we_should_search_hn(step_input: StepInput) -> bool:
    topic = step_input.input or step_input.previous_step_content or ""
    tech_keywords = [
        "ai",
        "machine learning",
        "programming",
        "software",
        "tech",
        "startup",
        "coding",
    ]
    return any(keyword in topic.lower() for keyword in tech_keywords)


def check_if_comprehensive_research_needed(step_input: StepInput) -> bool:
    topic = step_input.input or step_input.previous_step_content or ""
    comprehensive_keywords = [
        "comprehensive",
        "detailed",
        "thorough",
        "in-depth",
        "complete analysis",
        "full report",
        "extensive research",
    ]
    return any(keyword in topic.lower() for keyword in comprehensive_keywords)


# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Conditional Workflow with Multi-Step Condition",
    steps=[
        Parallel(
            Condition(
                name="HackerNewsCondition",
                description="Check if we should search Hacker News for tech topics",
                evaluator=check_if_we_should_search_hn,
                steps=[research_hackernews_step],
            ),
            Condition(
                name="ComprehensiveResearchCondition",
                description="Check if comprehensive multi-step research is needed",
                evaluator=check_if_comprehensive_research_needed,
                steps=[
                    deep_exa_analysis_step,
                    trend_analysis_step,
                    fact_verification_step,
                ],
            ),
            name="ConditionalResearch",
            description="Run conditional research steps in parallel",
        ),
        write_step,
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        # Sync Streaming
        workflow.print_response(
            input="Comprehensive analysis of climate change research",
            stream=True,
        )

        # Async
        asyncio.run(
            workflow.aprint_response(
                input="Comprehensive analysis of climate change research",
            )
        )
    except Exception as e:
        print(f"[ERROR] {e}")
    print()
