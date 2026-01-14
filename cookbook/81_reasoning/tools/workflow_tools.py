"""
1. Run: `pip install openai agno lancedb tantivy sqlalchemy` to install the dependencies
2. Export your OPENAI_API_KEY
3. Run: `python cookbook/reasoning/tools/knowledge_tools.py` to run the agent
"""

from textwrap import dedent

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.tools.workflow import WorkflowTools
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow

FEW_SHOT_EXAMPLES = dedent("""\
    You can refer to the examples below as guidance for how to use each tool.
    ### Examples
    #### Example: Blog Post Workflow
    User: Please create a blog post on the topic: AI trends in 2024
    Think: The user wants to process customer feedback data. I need to understand what format the data is in and what kind of summary they want. Let me start with a basic workflow run.
    Run: input_data="AI trends in 2024", additional_data={"topic": "AI, AI agents, AI workflows", "style": "The blog post should be written in a style that is easy to understand and follow."}
    Analyze: The workflow ran successfully and generated a basic blog post. However, the format might not be exactly what the user wants. Let me check if the results meet their expectations.
    Final Answer: I've created a blog post on the topic: AI trends in 2024 through the workflow. The blog post shows...
""")


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
    title = step_input.input
    topic = step_input.additional_data.get("topic")
    return StepOutput(
        content=dedent(f"""\
	I'm writing a blog post with the title: {title}
	<topic>
	{topic}
	</topic>
	Search the web for atleast 10 articles\
	""")
    )


def prepare_input_for_writer(step_input: StepInput) -> StepOutput:
    title = step_input.additional_data.get("title")
    topic = step_input.additional_data.get("topic")
    style = step_input.additional_data.get("style")

    research_team_output = step_input.previous_step_content

    return StepOutput(
        content=dedent(f"""\
	I'm writing a blog post with the title: {title}
	<required_style>
	{style}
	</required_style>
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
    members=[hackernews_agent, web_agent],
    instructions="Research tech topics from Hackernews and the web",
)


# Create and use workflow
if __name__ == "__main__":
    content_creation_workflow = Workflow(
        name="Blog Post Workflow",
        description="Automated blog post creation from Hackernews and the web",
        db=SqliteDb(
            session_table="workflow_session",
            db_file="tmp/workflow.db",
        ),
        steps=[
            prepare_input_for_web_search,
            research_team,
            prepare_input_for_writer,
            writer_agent,
        ],
    )

    workflow_tools = WorkflowTools(
        workflow=content_creation_workflow,
        enable_think=True,
        enable_analyze=True,
        add_few_shot=True,
        few_shot_examples=FEW_SHOT_EXAMPLES,
    )

    agent = Agent(
        model=OpenAIChat(id="gpt-5-mini"),
        tools=[workflow_tools],
        markdown=True,
    )

    agent.print_response(
        "Create a blog post with the following title: AI trends in 2024",
        instructions="When you run the workflow using the `run_workflow` tool, remember to pass `additional_data` as a dictionary of key-value pairs.",
        markdown=True,
        stream=True,
    )
