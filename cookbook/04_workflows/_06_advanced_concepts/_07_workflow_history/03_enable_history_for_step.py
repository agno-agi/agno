"""
This example shows step-level add_workflow_history control.
Only the Content Creator step gets workflow history to avoid repeating previous content.

Workflow: Research → Content Creation (with history) → Publishing
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

research_agent = Agent(
    name="Research Specialist",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are a research specialist who gathers information on topics.",
        "Conduct thorough research and provide key facts, trends, and insights.",
        "Focus on current, accurate information from reliable sources.",
        "Organize your findings in a clear, structured format.",
        "Provide citations and context for your research.",
    ],
)

content_creator = Agent(
    name="Content Creator",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are an expert content creator who writes engaging content.",
        "Use the research provided and CREATE UNIQUE content that stands out.",
        "IMPORTANT: Review workflow history to understand:",
        "- What content topics have been covered before",
        "- What writing styles and formats were used previously",
        "- User preferences and content patterns",
        "- Avoid repeating similar content or approaches",
        "Build on previous themes while keeping content fresh and original.",
        "Reference the conversation history to maintain consistency in tone and style.",
        "Create compelling headlines, engaging intros, and valuable content.",
    ],
)

publisher_agent = Agent(
    name="Content Publisher",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are a content publishing specialist.",
        "Review the created content and prepare it for publication.",
        "Add appropriate hashtags, formatting, and publishing recommendations.",
        "Suggest optimal posting times and distribution channels.",
        "Ensure content meets platform requirements and best practices.",
    ],
)

workflow = Workflow(
    name="Smart Content Creation Pipeline",
    description="Research → Content Creation (with history awareness) → Publishing",
    db=SqliteDb(db_file="tmp/content_workflow.db"),
    steps=[
        Step(
            name="Research Phase",
            agent=research_agent,
            add_workflow_history=True,  # Specifically add history to this step
        ),
        # Content creation step - uses workflow history to avoid repetition and give better results
        Step(
            name="Content Creation",
            agent=content_creator,
            add_workflow_history=True,  # Specifically add history to this step
        ),
        Step(
            name="Content Publishing",
            agent=publisher_agent,
        ),
    ],
)


if __name__ == "__main__":
    print("🎨 Content Creation Demo - Step-Level History Control")
    print("Only the Content Creator step sees previous workflow history!")
    print("")
    print("Try these content requests:")
    print("• 'Create a LinkedIn post about AI trends in 2024'")
    print("• 'Write a Twitter thread about productivity tips'")
    print("• 'Create a blog intro about remote work benefits'")
    print("")
    print(
        "Notice how the Content Creator references previous content to avoid repetition!"
    )
    print("Type 'exit' to quit")
    print("-" * 70)

    workflow.cli_app(
        session_id="content_demo",
        user="Content Requester",
        emoji="📝",
        stream=True,
    )
