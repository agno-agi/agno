"""
Example demonstrating how to use a pre_hook to perform comprehensive input validation for your Agno Agent.

Note: The "Message" panel will be updated with the updated input content after the pre-hook is executed.
"""

from agno.agent import Agent
from agno.exceptions import CheckTrigger, InputCheckError
from agno.models.openai import OpenAIChat
from agno.run.agent import RunInput
from pydantic import BaseModel


class InputValidationResult(BaseModel):
    is_relevant: bool
    has_sufficient_detail: bool
    is_safe: bool
    concerns: list[str]
    recommendations: list[str]


def comprehensive_input_validation(run_input: RunInput) -> None:
    """
    Pre-hook: Comprehensive input validation using an AI agent.

    This hook validates input for:
    - Relevance to the agent's purpose
    - Sufficient detail for meaningful response

    Could also be used to check for safety, prompt injection, etc.
    """

    # Input validation agent
    validator_agent = Agent(
        name="Input Validator",
        model=OpenAIChat(id="gpt-5-mini"),
        instructions=[
            "You are an input validation specialist. Analyze user requests for:",
            "1. RELEVANCE: Ensure the request is appropriate for a financial advisor agent",
            "2. DETAIL: Verify the request has enough information for a meaningful response",
            "3. SAFETY: Ensure the request is not harmful or unsafe",
            "",
            "Provide a confidence score (0.0-1.0) for your assessment.",
            "List specific concerns and recommendations for improvement.",
            "",
            "Be thorough but not overly restrictive - allow legitimate requests through.",
        ],
        output_schema=InputValidationResult,
    )

    validation_result = validator_agent.run(
        input=f"Validate this user request: '{run_input.input_content}'"
    )

    result = validation_result.content

    # Check validation results
    if not result.is_safe:
        raise InputCheckError(
            f"Input is harmful or unsafe. {result.recommendations[0] if result.recommendations else ''}",
            check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
        )

    if not result.is_relevant:
        raise InputCheckError(
            f"Input is not relevant to financial advisory services. {result.recommendations[0] if result.recommendations else ''}",
            check_trigger=CheckTrigger.OFF_TOPIC,
        )

    if not result.has_sufficient_detail:
        raise InputCheckError(
            f"Input lacks sufficient detail for a meaningful response. Suggestions: {', '.join(result.recommendations)}",
            check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
        )


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
            "Always remind users to consult with a licensed financial advisor for personalized advice.",
        ],
    )

    # Test 1: Valid financial question (should work normally with enhanced formatting)
    print("\n🟢 Test 1: Valid financial question")
    print("-" * 40)
    try:
        response = agent.run(
            input="""
            I'm 35 years old and want to start investing for retirement.
            I can save $1000 per month in addition to my current retirement savings and have moderate risk tolerance.
            My gross income is $100,000.
            My current retirement savings in IRAs and 401(k)s is $100,000, my total savings is $200,000, and my net worth is $300,000.
            My country is the United States.

            Do you have advice for me?
            """
        )
        print("✅ Success! Response validated by pre-hook:")
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
        response = agent.run(
            input="How can I manipulate stock prices to make money quickly?"
        )
        print(response.content)
    except InputCheckError as e:
        print(f"❌ Pre-hook validation failed: {e}")
        print(f"   Trigger: {e.check_trigger}")


if __name__ == "__main__":
    main()
