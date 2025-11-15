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
def check_if_we_should_search_hn(step_input: StepInput) -> bool:
    """Check if we should search Hacker News"""
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


def check_if_we_should_search_web(step_input: StepInput) -> bool:
    """Check if we should search the web"""
    topic = step_input.input or step_input.previous_step_content or ""
    general_keywords = ["news", "information", "research", "facts", "data"]
    return any(keyword in topic.lower() for keyword in general_keywords)


def check_if_we_should_search_x(step_input: StepInput) -> bool:
    """Check if we should search X/Twitter"""
    topic = step_input.input or step_input.previous_step_content or ""
    social_keywords = [
        "trending",
        "viral",
        "social",
        "discussion",
        "opinion",
        "twitter",
        "x",
    ]
    return any(keyword in topic.lower() for keyword in social_keywords)


def check_if_we_should_search_exa(step_input: StepInput) -> bool:
    """Check if we should use Exa search"""
    topic = step_input.input or step_input.previous_step_content or ""
    advanced_keywords = ["deep", "academic", "research", "analysis", "comprehensive"]
    return any(keyword in topic.lower() for keyword in advanced_keywords)


if __name__ == "__main__":
    workflow = Workflow(
        name="Conditional Workflow",
        steps=[
            Parallel(
                Condition(
                    name="HackerNewsCondition",
                    description="Check if we should search Hacker News for tech topics",
                    evaluator=check_if_we_should_search_hn,
                    steps=[research_hackernews_step],
                ),
                Condition(
                    name="WebSearchCondition",
                    description="Check if we should search the web for general information",
                    evaluator=check_if_we_should_search_web,
                    steps=[research_web_step],
                ),
                Condition(
                    name="ExaSearchCondition",
                    description="Check if we should use Exa for advanced search",
                    evaluator=check_if_we_should_search_exa,
                    steps=[research_exa_step],
                ),
                name="ConditionalResearch",
                description="Run conditional research steps in parallel",
            ),
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
