"""
This example shows how to use the add_workflow_history_to_steps flag to add workflow history to the steps.
In this case we have a single step workflow with a single agent.
The agent has access to the workflow history and uses it to provide personalized educational support.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ==============================================================================
# SIMPLE SINGLE-STEP TUTORING WORKFLOW
# ==============================================================================


tutor_agent = Agent(
    name="AI Tutor",
    model=OpenAIChat(id="gpt-4o"),
    instructions=[
        "You are an expert tutor who provides personalized educational support.",
        "You have access to our full conversation history.",
        "Build on previous discussions - don't repeat questions or information.",
        "Reference what the student has told you earlier in our conversation.",
        "Adapt your teaching style based on what you've learned about the student.",
        "Be encouraging, patient, and supportive.",
        "When asked about conversation history, provide a helpful summary.",
        "Focus on helping the student understand concepts and improve their skills.",
    ],
)

tutor_workflow = Workflow(
    name="Simple AI Tutor",
    description="Single-step conversational tutoring with history awareness",
    db=SqliteDb(db_file="tmp/simple_tutor_workflow.db"),
    steps=[
        Step(name="AI Tutoring", agent=tutor_agent),
    ],
    add_workflow_history_to_steps=True,  # This adds the workflow history
)


def demo_simple_tutoring_cli():
    """Demo simple single-step tutoring workflow"""
    print("🎓 Simple AI Tutor Demo - Type 'exit' to quit")
    print("Try asking about:")
    print("• 'I'm struggling with calculus derivatives'")
    print("• 'Can you help me with algebra?'")
    print("-" * 60)

    tutor_workflow.cli_app(
        session_id="simple_tutor_demo",
        user="Student",
        emoji="📚",
        stream=True,
        show_step_details=True,
    )


if __name__ == "__main__":
    demo_simple_tutoring_cli()
