from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.exa import ExaTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.condition import Condition
from agno.workflow.parallel import Parallel
from agno.workflow.step import Step
from agno.workflow.steps import Steps
from agno.workflow.workflow import Workflow

# Define agents for different tasks
researcher = Agent(
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    instructions="Research the given topic and provide key facts and insights.",
)

tech_researcher = Agent(
    name="Tech Research Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    instructions="Research tech-related topics from Hacker News and provide latest developments.",
)

news_researcher = Agent(
    name="News Research Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[ExaTools()],
    instructions="Research current news and trends using Exa search.",
)

writer = Agent(
    name="Writing Agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions="Write a comprehensive article based on the research provided. Make it engaging and well-structured.",
)

editor = Agent(
    name="Editor Agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions="Review and edit the article for clarity, grammar, and flow. Provide a polished final version.",
)

content_agent = Agent(
    name="Content Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Prepare and format content for writing based on research inputs.",
)

# Define individual steps
initial_research_step = Step(
    name="InitialResearch",
    agent=researcher,
    description="Initial research on the topic",
)


# Condition evaluator function
def is_tech_topic(step_input) -> bool:
    """Check if the topic is tech-related and needs specialized research"""
    message = step_input.input.lower() if step_input.input else ""
    tech_keywords = [
        "ai",
        "machine learning",
        "technology",
        "software",
        "programming",
        "tech",
        "startup",
        "blockchain",
    ]
    return any(keyword in message for keyword in tech_keywords)


# Define parallel research steps
tech_research_step = Step(
    name="TechResearch",
    agent=tech_researcher,
    description="Research tech developments from Hacker News",
)

news_research_step = Step(
    name="NewsResearch",
    agent=news_researcher,
    description="Research current news and trends",
)

# Define content preparation step
content_prep_step = Step(
    name="ContentPreparation",
    agent=content_agent,
    description="Prepare and organize all research for writing",
)

writing_step = Step(
    name="Writing",
    agent=writer,
    description="Write an article based on the research",
)

editing_step = Step(
    name="Editing",
    agent=editor,
    description="Edit and polish the article",
)

# Create a Steps sequence with a Condition containing Parallel steps
article_creation_sequence = Steps(
    name="ArticleCreation",
    description="Complete article creation workflow from research to final edit",
    steps=[
        initial_research_step,
        # Condition with Parallel steps inside
        Condition(
            name="TechResearchCondition",
            description="If topic is tech-related, do specialized parallel research",
            evaluator=is_tech_topic,
            steps=[
                Parallel(
                    tech_research_step,
                    news_research_step,
                    name="SpecializedResearch",
                    description="Parallel tech and news research",
                ),
                content_prep_step,
            ],
        ),
        writing_step,
        editing_step,
    ],
)

# Create and use workflow
if __name__ == "__main__":
    article_workflow = Workflow(
        name="Enhanced Article Creation Workflow",
        description="Automated article creation with conditional parallel research",
        steps=[article_creation_sequence],
    )

    article_workflow.print_response(
        input="Write an article about the latest AI developments in machine learning",
        markdown=True,
        stream=True,
    )
