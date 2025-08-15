from typing import List

from agno.agent import Agent
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow import Loop, Parallel, Step, Workflow
from agno.workflow.types import StepOutput

# Create agents for research
research_agent = Agent(
    name="Research Agent",
    role="Research specialist",
    tools=[HackerNewsTools(), DuckDuckGoTools()],
    instructions="You are a research specialist. Research the given topic thoroughly.",
    markdown=True,
)

analysis_agent = Agent(
    name="Analysis Agent",
    role="Data analyst",
    instructions="You are a data analyst. Analyze and summarize research findings.",
    markdown=True,
)

content_agent = Agent(
    name="Content Agent",
    role="Content creator",
    instructions="You are a content creator. Create engaging content based on research.",
    markdown=True,
)

# Create research steps
research_hackernews_step = Step(
    name="Research HackerNews",
    agent=research_agent,
    description="Research trending topics on HackerNews",
)

research_web_step = Step(
    name="Research Web",
    agent=research_agent,
    description="Research additional information from web sources",
)

# Create analysis steps
trend_analysis_step = Step(
    name="Trend Analysis",
    agent=analysis_agent,
    description="Analyze trending patterns in the research",
)

sentiment_analysis_step = Step(
    name="Sentiment Analysis",
    agent=analysis_agent,
    description="Analyze sentiment and opinions from the research",
)

content_step = Step(
    name="Create Content",
    agent=content_agent,
    description="Create content based on research findings",
)


# End condition function
def research_evaluator(outputs: List[StepOutput]) -> bool:
    """
    Evaluate if research results are sufficient
    Returns True to break the loop, False to continue
    """
    # Check if we have good research results
    if not outputs:
        return False

    # Calculate total content length from all outputs
    total_content_length = sum(len(output.content or "") for output in outputs)

    # Check if we have substantial content (more than 500 chars total)
    if total_content_length > 500:
        print(
            f"✅ Research evaluation passed - found substantial content ({total_content_length} chars total)"
        )
        return True

    print(
        f"❌ Research evaluation failed - need more substantial research (current: {total_content_length} chars)"
    )
    return False


# Create workflow with loop containing parallel steps
workflow = Workflow(
    name="Advanced Research and Content Workflow",
    description="Research topics with parallel execution in a loop until conditions are met, then create content",
    steps=[
        Loop(
            name="Research Loop with Parallel Execution",
            steps=[
                Parallel(
                    research_hackernews_step,
                    research_web_step,
                    trend_analysis_step,
                    name="Parallel Research & Analysis",
                    description="Execute research and analysis in parallel for efficiency",
                ),
                sentiment_analysis_step,
            ],
            end_condition=research_evaluator,
            max_iterations=3,  # Maximum 3 iterations
        ),
        content_step,
    ],
)

if __name__ == "__main__":
    workflow.print_response(
        input="Research the latest trends in AI and machine learning, then create a summary",
    )
