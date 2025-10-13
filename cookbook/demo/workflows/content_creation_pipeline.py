"""Content Creation Pipeline - Workflow for automated content research, writing, editing, and publishing"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai.chat import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.newspaper4k import Newspaper4kTools
from agno.workflow.step import Step
from agno.workflow.types import StepOutput, WorkflowExecutionInput
from agno.workflow.workflow import Workflow
from pydantic import BaseModel, Field

from agno.db.sqlite.sqlite import SqliteDb

db = SqliteDb(id="real-world-db", db_file="tmp/real_world.db")


class ContentBrief(BaseModel):
    """Structured content brief"""

    topic: str
    target_audience: str
    tone: str
    word_count: int
    key_points: list[str]
    seo_keywords: list[str]


researcher = Agent(
    name="Content Researcher",
    role="Researches topics and gathers information",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Expert researcher who finds accurate, relevant information from multiple sources",
    instructions=[
        "Search for the most recent and authoritative information on the topic",
        "Find 5-10 high-quality sources",
        "Verify facts across multiple sources",
        "Identify trending angles and unique perspectives",
        "Compile key statistics, quotes, and examples",
        "Note any controversies or differing viewpoints",
        "Remember past research topics and sources",
        "Track trending topics and content preferences",
    ],
    tools=[DuckDuckGoTools()],
    enable_user_memories=True,
    add_history_to_context=True,
    num_history_runs=5,
    add_datetime_to_context=True,
    db=db,
    markdown=True,
)

content_writer = Agent(
    name="Content Writer",
    role="Writes engaging, high-quality content",
    model=Claude(id="claude-sonnet-4-20250514"),
    description="Professional content writer specializing in engaging, SEO-optimized articles",
    instructions=[
        "Write in the specified tone and style for the target audience",
        "Create compelling headlines and subheadings",
        "Use storytelling techniques to engage readers",
        "Incorporate research findings naturally",
        "Include relevant examples and case studies",
        "Optimize for SEO without sacrificing readability",
        "Maintain consistent voice throughout",
        "Use clear, concise language",
        "Remember brand voice and writing style preferences",
        "Track successful content patterns and topics",
    ],
    tools=[Newspaper4kTools()],
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=8,
    add_datetime_to_context=True,
    db=db,
    markdown=True,
)

content_editor = Agent(
    name="Content Editor",
    role="Edits and refines content for quality",
    model=OpenAIChat(id="gpt-4o"),
    description="Meticulous editor focused on clarity, grammar, and engagement",
    instructions=[
        "Check for grammar, spelling, and punctuation errors",
        "Improve sentence structure and flow",
        "Ensure logical organization and transitions",
        "Verify factual accuracy and source credibility",
        "Enhance clarity and readability",
        "Strengthen weak sections",
        "Check tone consistency",
        "Ensure proper formatting",
        "Provide constructive feedback",
    ],
    markdown=True,
)


async def content_creation_executor(execution_input: WorkflowExecutionInput) -> StepOutput:
    """Custom executor for content creation pipeline"""
    topic = str(execution_input.input)  # Get the topic from input

    print(f"\n📝 Starting content creation for: {topic}")

    # Phase 1: Research
    print("\n🔍 Phase 1: Research")
    research_result = await researcher.arun(
        f"Research this topic comprehensively: {topic}. Find key statistics, trends, and expert opinions."
    )
    research = research_result.content

    # Phase 2: Writing
    print("\n✍️  Phase 2: Writing")
    write_result = await content_writer.arun(
        f"Write a comprehensive article on: {topic}\n\n"
        f"Use this research:\n{research}\n\n"
        f"Create engaging, well-structured content with examples."
    )
    draft = write_result.content

    # Phase 3: Editing
    print("\n✅ Phase 3: Editing")
    edited_result = await content_editor.arun(
        f"Edit and refine this article:\n\n{draft}\n\n"
        f"Improve clarity, fix errors, enhance readability."
    )
    final_content = edited_result.content

    return final_content


content_creation_workflow = Workflow(
    name="Content Creation Pipeline",
    description=dedent("""\
        Automated content creation workflow that researches, writes, edits,
        and prepares content for publishing. Features memory to remember brand voice,
        past topics, and content preferences for consistent, high-quality output.\
    """),
    steps=[Step(name="Content Creation", executor=content_creation_executor)],
    db=db,
)
