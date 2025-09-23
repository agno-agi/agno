from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.workflow.step import Step, StepInput, StepOutput
from agno.workflow.workflow import Workflow


# ==============================================================================
# SIMPLE SINGLE-STEP TUTORING WORKFLOW
# ==============================================================================

def create_simple_tutoring_workflow():
    """Simple single-step tutoring workflow with conversation history"""
    
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
            "Focus on helping the student understand concepts and improve their skills."
        ],
        db=SqliteDb(db_file="tmp/tutor_agent_session.db"),
    )

    return Workflow(
        name="Simple AI Tutor",
        description="Single-step conversational tutoring with history awareness",
        db=SqliteDb(db_file="tmp/simple_tutor_workflow.db"),
        steps=[
            Step(name="AI Tutoring", agent=tutor_agent),
        ],
        add_history_to_context_for_steps=True,  
    )


def demo_simple_tutoring_cli():
    """Demo simple single-step tutoring workflow"""
    tutor_workflow = create_simple_tutoring_workflow()
    
    print("🎓 Simple AI Tutor Demo - Type 'exit' to quit")
    print("Try asking about:")
    print("• 'I'm struggling with calculus derivatives'")
    print("• 'Can you help me with algebra?'") 
    print("• 'What did I tell you about my math level?'")
    print("• 'What is my conversation history?'")
    print("-" * 60)
    
    tutor_workflow.cli_app(
        session_id="simple_tutor_demo",
        user="Student",
        emoji="📚",
        stream_intermediate_steps=True,
        show_step_details=True,
    )


if __name__ == "__main__":
    demo_simple_tutoring_cli()