"""
Example demonstrating how to use pre_hook and post_hook with Agno Agent.

This example shows how to:
1. Pre-hook: Comprehensive input validation using an AI agent
2. Post-hook: Enhanced output formatting and structure
"""

from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.utils.log import log_debug


def transform_input(input: Any) -> None:
    """
    Pre-hook: Rewrite the input to be more relevant to the agent's purpose.
    
    This hook rewrites the input to be more relevant to the agent's purpose.
    """
    log_debug(f"Transforming input: {input}")
    
    # Input transformation agent
    transformer_agent = Agent(
        name="Input Transformer",
        model=OpenAIChat(id="gpt-5-mini"),
        instructions=[
            "You are an input transformation specialist.",
            "Rewrite the user request to be more relevant to the agent's purpose.",
            "Use known context engineering standards to rewrite the input.",
            "Keep the input as concise as possible.",
        ],
    )
    
    transformation_result = transformer_agent.run(
        input=f"Transform this user request: '{input}'"
    )
    
    # Overwrite the input with the transformed input
    input = transformation_result.content
    log_debug(f"Transformed input: {input}")
    


def main():
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
            "Always remind users to consult with a licensed financial advisor for personalized advice."
        ],
        debug_mode=True,
    )

    try:
        response = agent.run(
            input="I'm 35 years old and want to start investing for retirement. moderate risk tolerance. retirement savings in IRAs/401(k)s= $100,000. total savings is $200,000. my net worth is $300,000"
        )
        print("✅ Success! Response transformed by pre-hook:")
        print(response.content)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")


if __name__ == "__main__":
    main()
