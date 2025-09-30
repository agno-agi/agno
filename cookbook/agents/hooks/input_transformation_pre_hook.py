"""Example demonstrating how to use a pre_hook to transform the input of your Agno Agent."""

from typing import Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunInput
from agno.session.agent import AgentSession
from agno.utils.log import log_debug


def transform_input(
    run_input: RunInput,
    session: AgentSession,
    user_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
) -> None:
    """
    Pre-hook: Rewrite the input to be more relevant to the agent's purpose.

    This hook rewrites the input to be more relevant to the agent's purpose.
    """
    log_debug(
        f"Transforming input: {run_input.input_content} for user {user_id} and session {session.session_id}"
    )

    # Input transformation agent
    transformer_agent = Agent(
        name="Input Transformer",
        model=OpenAIChat(id="gpt-5-mini"),
        instructions=[
            "You are an input transformation specialist.",
            "Rewrite the user request to be more relevant to the agent's purpose.",
            "Use known context engineering standards to rewrite the input.",
            "Keep the input as concise as possible.",
            "The agent's purpose is to provide investment guidance and financial planning advice.",
        ],
        debug_mode=debug_mode,
    )

    transformation_result = transformer_agent.run(
        input=f"Transform this user request: '{run_input.input_content}'"
    )

    # Overwrite the input with the transformed input
    run_input.input_content = transformation_result.content
    log_debug(f"Transformed input: {run_input.input_content}")


print("🚀 Input Transformation Pre-Hook Example")
print("=" * 60)

# Create a financial advisor agent with comprehensive hooks
agent = Agent(
    name="Financial Advisor",
    model=OpenAIChat(id="gpt-5-mini"),
    pre_hooks=[transform_input],
    description="A professional financial advisor providing investment guidance and financial planning advice.",
    instructions=[
        "You are a knowledgeable financial advisor with expertise in:",
        "• Investment strategies and portfolio management",
        "• Retirement planning and savings strategies",
        "• Risk assessment and diversification",
        "• Tax-efficient investing",
        "",
        "Provide clear, actionable advice while being mindful of individual circumstances.",
        "Always remind users to consult with a licensed financial advisor for personalized advice.",
    ],
    debug_mode=True,
)

agent.print_response(
    input="I'm 35 years old and want to start investing for retirement. moderate risk tolerance. retirement savings in IRAs/401(k)s= $100,000. total savings is $200,000. my net worth is $300,000",
    session_id="test_session",
    user_id="test_user",
    stream=True,
)
