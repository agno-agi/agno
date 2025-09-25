"""
Simple example showing custom function steps with workflow history access.
Demonstrates: Agent Response → Custom Function Analysis → Agent Follow-up
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow


def analyze_conversation_context(step_input: StepInput) -> StepOutput:
    """
    Custom function that analyzes conversation history.
    This runs AFTER the first agent, so it has history to analyze.
    """
    current_request = step_input.input or ""

    # Get the conversation history that was created by previous steps
    history = step_input.get_workflow_history(num_runs=3)

    print("---------------- history ----------------")
    print(history)
    print("---------------- history ----------------")

    # Get the previous step output (what the agent just said)
    previous_step_content = step_input.get_last_step_content() or ""

    # Analyze the conversation
    analysis = f"""
        CONVERSATION ANALYSIS REPORT:
        ============================

        Original User Request: {current_request}

        Agent Response: {previous_step_content[:200]}{"..." if len(previous_step_content) > 200 else ""}

        Full Conversation History:
        {history if history else "No previous history available"}

        INSIGHTS:
        - Has Conversation History: {"Yes" if history else "No"}
        - Total History Length: {len(history) if history else 0} characters
        - Agent Mentioned Keywords: {", ".join([word for word in ["python", "learning", "help", "example"] if word in previous_step_content.lower()])}
        - Conversation Continuity: {"Good - building on previous topics" if history and len(history) > 100 else "New conversation"}

        SUMMARY:
        This analysis shows how custom functions can access and analyze the full conversation context, including what agents have said in previous steps and historical conversations.
    """

    # you can pass this history as input to agent.run(input=history) in this custom python function if needed

    return StepOutput(content=analysis.strip())


def create_simple_workflow():
    """Simple workflow: Agent Response → Custom Function Analysis → Agent Follow-up"""

    # Step 1: Initial Agent responds to user input
    response_step = Step(
        name="AI Assistant Response",
        agent=Agent(
            name="AI Assistant",
            model=OpenAIChat(id="gpt-4o"),
            instructions=[
                "You are a helpful AI assistant.",
                "Provide helpful responses to user questions.",
                "Use conversation history when available to give contextual answers.",
                "Be conversational and reference previous topics when relevant.",
            ],
        ),
    )

    # Step 2: Custom function analyzes what just happened + history
    analysis_step = Step(
        name="Conversation Analysis",
        executor=analyze_conversation_context,
        description="Analyze conversation history and agent responses",
    )

    # Step 3: Follow-up Agent continues the conversation naturally
    followup_step = Step(
        name="Conversation Continuator",
        agent=Agent(
            name="Conversation Continuator",
            model=OpenAIChat(id="gpt-4o"),
            instructions=[
                "You are a follow-up assistant that continues conversations naturally.",
                "You can see the analysis of the conversation that just happened.",
                "Use this analysis to provide additional insights, ask follow-up questions, or offer next steps.",
                "Keep the conversation engaging and helpful.",
                "Reference the conversation history and analysis when relevant.",
                "Don't just repeat what was already said - add value to the conversation.",
            ],
        ),
    )

    return Workflow(
        name="Natural Conversational Workflow",
        description="AI agent response → custom function analysis → agent follow-up for natural flow",
        db=SqliteDb(db_file="tmp/simple_workflow.db"),
        steps=[response_step, analysis_step, followup_step],
        add_workflow_history=True,
    )


def demo_simple_workflow():
    """Demo the natural conversational workflow"""
    workflow = create_simple_workflow()

    print("🤖 Natural Conversational Workflow Demo")
    print("Order: AI Agent Response → Custom Function Analysis → Agent Follow-up")
    print("")
    print("Try a conversation to see the full flow:")
    print("- 'Hello, I want to learn about machine learning'")
    print("- 'What's the weather like today?'")
    print("")
    print("Type 'exit' to quit")
    print("-" * 60)

    workflow.cli_app(
        session_id="natural_demo",
        user="User",
        emoji="💬",
        stream=True,
        stream_intermediate_steps=True,
    )


if __name__ == "__main__":
    demo_simple_workflow()
