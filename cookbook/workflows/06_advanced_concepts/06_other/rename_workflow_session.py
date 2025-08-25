from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
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

writer = Agent(
    name="Writing Agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions="Write a comprehensive article based on the research provided. Make it engaging and well-structured.",
)

# Define individual steps
research_step = Step(
    name="research",
    agent=researcher,
    description="Research the topic and gather information",
)

writing_step = Step(
    name="writing",
    agent=writer,
    description="Write an article based on the research",
)


# Create a Steps sequence that chains these above steps together
article_creation_sequence = Steps(
    name="article_creation",
    description="Complete article creation workflow from research to writing",
    steps=[research_step, writing_step],
)

# Create and use workflow
if __name__ == "__main__":
    article_workflow = Workflow(
        description="Automated article creation from research to writing",
        steps=[article_creation_sequence],
        debug_mode=True,
    )

    article_workflow.print_response(
        input="Write an article about the benefits of renewable energy",
        markdown=True,
    )

    article_workflow.set_session_name(autogenerate=True)

    # print the new session name
    print(f"New session name: {article_workflow.session_name}")
