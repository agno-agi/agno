from textwrap import dedent
from typing import Dict, List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.hackernews import HackerNewsTools
from agno.tools.parallel import ParallelTools
from agno.tools.reasoning import ReasoningTools
from agno.workflow import Step, Workflow
from agno.workflow.parallel import Parallel
from agno.workflow.step import StepInput, StepOutput
from db import demo_db

# ============================================================================
# Create Research Agents
# ============================================================================
hn_researcher = Agent(
    name="HN Researcher",
    role="Research trending topics and discussions on Hacker News",
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[HackerNewsTools()],
    description=dedent("""\
        You are the HN Researcher — an agent that searches Hacker News for relevant discussions,
        trending topics, and technical insights from the developer community.
        """),
    instructions=dedent("""\
        1. Search Hacker News for relevant stories, discussions, and comments on the given topic.
        2. Focus on highly-voted stories and insightful comments.
        3. Identify key themes, opinions, and technical details from the community.
        4. Summarize your findings in a clear, organized format with links to sources.
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)

web_researcher = Agent(
    name="Web Researcher",
    role="Search the web for current information and sources",
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[DuckDuckGoTools()],
    description=dedent("""\
        You are the Web Researcher — an agent that searches the web for up-to-date information,
        news articles, and credible sources on any topic.
        """),
    instructions=dedent("""\
        1. Search the web for recent and relevant information on the given topic.
        2. Prioritize credible sources like news sites, official documentation, and reputable publications.
        3. Gather diverse perspectives and factual information.
        4. Summarize findings with clear citations and links.
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)

parallel_researcher = Agent(
    name="Parallel Researcher",
    role="Perform deep semantic search for high-quality content",
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[ParallelTools(enable_search=True, enable_extract=True)],
    description=dedent("""\
        You are the Parallel Researcher — an agent that uses semantic search to find
        high-quality, relevant content from across the web.
        """),
    instructions=dedent("""\
        1. Use Parallel's search and extract tools to find highly relevant, quality content.
        2. Focus on authoritative sources, in-depth articles, and expert analysis.
        3. Provide context and summaries of the most valuable findings.
        4. Include links to all sources.
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)

# ============================================================================
# Create Writer and Reviewer Agents
# ============================================================================
writer = Agent(
    name="Writer",
    role="Synthesize research into compelling content",
    model=OpenAIChat(id="gpt-5-mini"),
    tools=[ReasoningTools()],
    description=dedent("""\
        You are the Writer — an agent that synthesizes research findings into clear,
        engaging, and well-structured content.
        """),
    instructions=dedent("""\
        **Input:** The consolidated research from the Research Phase.
        **Output:** A well-structured and engaging report on the user's request.
        **Instructions:**
        1. Analyze and consolidate all the research findings that you have received.
        2. Identify key themes, insights, and important details.
        3. Structure the content logically with clear sections and sub-sections.
        4. Write in a clear, engaging style appropriate for the topic.
        5. Include relevant citations and links from the research.
        6. Use reasoning tools to think through complex topics and structure the content.
        """),
    add_history_to_context=True,
    markdown=True,
    db=demo_db,
)


async def consolidate_research_step_function(input: StepInput) -> StepOutput:
    """Consolidate the research from the different agents"""
    # Get all previous step outputs
    previous_step_outputs: Optional[Dict[str, StepOutput]] = input.previous_step_outputs
    # Get the parallel step output
    parallel_step_output: Optional[StepOutput] = (
        previous_step_outputs.get("Research Phase") if previous_step_outputs else None
    )
    # Get the list of step outputs from the parallel step
    parallel_step_output_list: Optional[List[StepOutput]] = (
        parallel_step_output.steps if parallel_step_output else None
    )
    # Create the research content by combining the content of the different step outputs
    research_content = "Please use the following extracted research create a comprehensive report on the user's request. \n\n"
    if parallel_step_output_list and len(parallel_step_output_list) > 0:
        for step_output in parallel_step_output_list:
            research_content += (
                f"## {step_output.step_name} \n\n{step_output.content}\n\n"
            )

        return StepOutput(content=research_content, success=True)

    return StepOutput(content="No research content found", success=False)


# ============================================================================
# Create Workflow Steps
# ============================================================================
hn_research_step = Step(
    name="HN Research",
    agent=hn_researcher,
)
web_research_step = Step(
    name="Web Research",
    agent=web_researcher,
)
parallel_research_step = Step(
    name="Parallel Research",
    agent=parallel_researcher,
)
researcher_steps: List[Step] = [
    hn_research_step,
    web_research_step,
    parallel_research_step,
]

research_consolidation_step = Step(
    name="Consolidate Research",
    executor=consolidate_research_step_function,
)

writer_step = Step(
    name="Writer",
    agent=writer,
)

# ============================================================================
# Create the Workflow
# ============================================================================
research_workflow = Workflow(
    name="Research Workflow",
    description=dedent("""\
        A parallel workflow that researches information from multiple sources simultaneously,
        then synthesizes and reviews the information for publication.
        """),
    steps=[
        Parallel(*researcher_steps, name="Research Phase"),  # type: ignore
        research_consolidation_step,
        writer_step,
    ],
    db=demo_db,
)
