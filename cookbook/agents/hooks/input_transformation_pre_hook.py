"""
Example demonstrating how to use pre_hook and post_hook with Agno Agent.

This example shows how to:
1. Pre-hook: Comprehensive input validation using an AI agent
2. Post-hook: Enhanced output formatting and structure
"""

from typing import Any

from agno.agent import Agent
from agno.exceptions import InputCheckError
from agno.checks import CheckTrigger
from agno.models.openai import OpenAIChat
from pydantic import BaseModel


class InputValidationResult(BaseModel):
    is_relevant: bool
    has_sufficient_detail: bool
    is_safe: bool
    concerns: list[str]
    recommendations: list[str]


def comprehensive_input_validation(input: Any) -> None:
    """
    Pre-hook: Rewrite the input to be more relevant to the agent's purpose.
    
    This hook rewrites the input to be more relevant to the agent's purpose.
    """
    
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
        input=f"Validate this user request: '{input}'"
    )
    
    # Overwrite the input with the transformed input
    input = transformation_result.content
    


def main():
    print("🚀 Input Validation Pre-Hook Example")
    print("=" * 60)

    # Create a financial advisor agent with comprehensive hooks
    agent = Agent(
        name="Financial Advisor",
        model=OpenAIChat(id="gpt-5-mini"),
        pre_hooks=[comprehensive_input_validation],
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
    )

    # Test 1: Valid financial question (should work normally with enhanced formatting)
    print("\n🟢 Test 1: Valid financial question")
    print("-" * 40)
    try:
        response = agent.run(
            input="I'm 35 years old and want to start investing for retirement. I can save $1000 per month and have moderate risk tolerance. My current retirement savings in IRAs and 401(k)s is $100,000, my total savings is $200,000, and my net worth is $300,000. Do you have advice for me?"
        )
        print("✅ Success! Response formatted by post-hook:")
        print(response.content)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

    # Test 2: Input with insufficient detail (should trigger pre-hook)
    print("\n🔴 Test 2: Vague input (insufficient detail)")
    print("-" * 40)
    try:
        response = agent.run(input="Help me invest")
        print(response.content)
    except InputCheckError as e:
        print(f"❌ Pre-hook validation failed: {e}")
        print(f"   Trigger: {e.check_trigger}")

    # Test 3: Irrelevant request (should trigger pre-hook)
    print("\n🔴 Test 3: Off-topic request")
    print("-" * 40)
    try:
        response = agent.run(input="What's the best pizza recipe?")
        print(response.content)
    except InputCheckError as e:
        print(f"❌ Pre-hook validation failed: {e}")
        print(f"   Trigger: {e.check_trigger}")

    # Test 4: Potentially harmful content (should trigger pre-hook)
    print("\n🔴 Test 4: Potentially unsafe content")
    print("-" * 40)
    try:
        response = agent.run(input="How can I manipulate stock prices to make money quickly?")
        print(response.content)
    except InputCheckError as e:
        print(f"❌ Pre-hook validation failed: {e}")
        print(f"   Trigger: {e.check_trigger}")


if __name__ == "__main__":
    main()
