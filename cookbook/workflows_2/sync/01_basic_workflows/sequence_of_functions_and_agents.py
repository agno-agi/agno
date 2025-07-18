from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.storage.sqlite import SqliteStorage
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.workflow.v2.types import StepInput, StepOutput
from agno.workflow.v2.workflow import Workflow

# Define agents
web_agent = Agent(
    name="Web Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[DuckDuckGoTools()],
    role="Search the web for the latest news and trends",
)
hackernews_agent = Agent(
    name="Hackernews Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[HackerNewsTools()],
    role="Extract key insights and content from Hackernews posts",
)

writer_agent = Agent(
    name="Writer Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Write a blog post on the topic",
)


def prepare_input_for_web_search(step_input: StepInput) -> StepOutput:
    topic = step_input.message
    return StepOutput(
        content=dedent(f"""\
	I'm writing a blog post on the topic
	<topic>
	{topic}
	</topic>
	
	Search the web for atleast 10 articles\
	""")
    )


def prepare_input_for_writer(step_input: StepInput) -> StepOutput:
    topic = step_input.message
    research_team_output = step_input.previous_step_content

    return StepOutput(
        content=dedent(f"""\
	I'm writing a blog post on the topic:
	<topic>
	{topic}
	</topic>
    
	Here is information from the web:
	<research_results>
	{research_team_output}
	<research_results>\
	""")
    )


# Define research team for complex analysis
research_team = Team(
    name="Research Team",
    mode="coordinate",
    members=[hackernews_agent, web_agent],
    instructions="Research tech topics from Hackernews and the web",
)


# Create and use workflow
if __name__ == "__main__":
    content_creation_workflow = Workflow(
        name="Blog Post Workflow",
        description="Automated blog post creation from Hackernews and the web",
        storage=SqliteStorage(
            table_name="workflow_v2",
            db_file="tmp/workflow_v2.db",
            mode="workflow_v2",
        ),
        steps=[
            prepare_input_for_web_search,
            research_team,
            prepare_input_for_writer,
            writer_agent,
        ],
    )
    content_creation_workflow.print_response(
        message="AI trends in 2024",
        markdown=True,
    )
