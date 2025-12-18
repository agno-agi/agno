import asyncio

from agno.agent.agent import Agent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.exa import ExaTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.condition import Condition
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow

# === AGENTS ===
hackernews_agent = Agent(
    name="HackerNews Researcher",
    instructions="Research tech news and trends from Hacker News",
    tools=[HackerNewsTools()],
)

web_agent = Agent(
    name="Web Researcher",
    instructions="Research general information from the web",
    tools=[DuckDuckGoTools()],
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

# === RESEARCH STEPS ===
research_hackernews_step = Step(
    name="ResearchHackerNews",
    description="Research tech news from Hacker News",
    agent=hackernews_agent,
)

research_web_step = Step(
    name="ResearchWeb",
    description="Research general information from web",
    agent=web_agent,
)

research_exa_step = Step(
    name="ResearchExa",
    description="Research using Exa search",
    agent=exa_agent,
)

prepare_input_for_write_step = Step(
    name="PrepareInput",
    description="Prepare and organize research data for writing",
    agent=content_agent,
)

write_step = Step(
    name="WriteContent",
    description="Write the final content based on research",
    agent=content_agent,
)


# === CONDITION EVALUATORS ===
def should_conduct_research(step_input: StepInput) -> bool:
    """Check if we should conduct comprehensive research"""
    topic = step_input.input or step_input.previous_step_content or ""

    # Keywords that indicate research is needed
    research_keywords = [
        "ai",
        "machine learning",
        "programming",
        "software",
        "tech",
        "startup",
        "coding",
        "news",
        "information",
        "research",
        "facts",
        "data",
        "analysis",
        "comprehensive",
        "trending",
        "viral",
        "social",
        "discussion",
        "opinion",
        "developments",
    ]

    # If the topic contains any research-worthy keywords, conduct research
    return any(keyword in topic.lower() for keyword in research_keywords)


def is_tech_related(step_input: StepInput) -> bool:
    """Check if the topic is tech-related for additional tech research"""
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


if __name__ == "__main__":
    workflow = Workflow(
        name="Conditional Research Workflow",
        description="Conditionally execute parallel research based on topic relevance",
        steps=[
            # Main research condition - if topic needs research, run parallel research steps
            Condition(
                name="ResearchCondition",
                description="Check if comprehensive research is needed for this topic",
                evaluator=should_conduct_research,
                steps=[
                    Parallel(
                        research_hackernews_step,
                        research_web_step,
                        name="ComprehensiveResearch",
                        description="Run multiple research sources in parallel",
                    ),
                    research_exa_step,
                ],
            ),
            # # Additional tech-specific research if needed
            Condition(
                name="TechResearchCondition",
                description="Additional tech-focused research if topic is tech-related",
                evaluator=is_tech_related,
                steps=[
                    Step(
                        name="TechAnalysis",
                        description="Deep dive tech analysis and trend identification",
                        agent=content_agent,
                    ),
                ],
            ),
            # Content preparation and writing
            prepare_input_for_write_step,
            write_step,
        ],
    )

    try:
        asyncio.run(
            workflow.aprint_response(
                input="Latest AI developments in machine learning",
                stream=True,
            )
        )
    except Exception as e:
        print(f"❌ Error: {e}")
    print()
