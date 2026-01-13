"""
Example demonstrating output validation using post-hooks with Agno Agent.

This example shows how to:
1. Validate agent responses for quality and safety
2. Ensure outputs meet minimum standards before being returned
3. Raise OutputCheckError when validation fails
"""

import asyncio

from agno.agent import Agent
from agno.exceptions import CheckTrigger, OutputCheckError
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from pydantic import BaseModel


class OutputValidationResult(BaseModel):
    is_complete: bool
    is_professional: bool
    is_safe: bool
    concerns: list[str]
    confidence_score: float


def validate_response_quality(run_output: RunOutput) -> None:
    """
    Post-hook: Validate the agent's response for quality and safety.

    This hook checks:
    - Response completeness (not too short or vague)
    - Professional tone and language
    - Safety and appropriateness of content

    Raises OutputCheckError if validation fails.
    """

    # Skip validation for empty responses
    if not run_output.content or len(run_output.content.strip()) < 10:
        raise OutputCheckError(
            "Response is too short or empty",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )

    # Create a validation agent
    validator_agent = Agent(
        name="Output Validator",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=[
            "You are an output quality validator. Analyze responses for:",
            "1. COMPLETENESS: Response addresses the question thoroughly",
            "2. PROFESSIONALISM: Language is professional and appropriate",
            "3. SAFETY: Content is safe and doesn't contain harmful advice",
            "",
            "Provide a confidence score (0.0-1.0) for overall quality.",
            "List any specific concerns found.",
            "",
            "Be reasonable - don't reject good responses for minor issues.",
        ],
        output_schema=OutputValidationResult,
    )

    validation_result = validator_agent.run(
        input=f"Validate this response: '{run_output.content}'"
    )

    result = validation_result.content

    # Check validation results and raise errors for failures
    if not result.is_complete:
        raise OutputCheckError(
            f"Response is incomplete. Concerns: {', '.join(result.concerns)}",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )

    if not result.is_professional:
        raise OutputCheckError(
            f"Response lacks professional tone. Concerns: {', '.join(result.concerns)}",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )

    if not result.is_safe:
        raise OutputCheckError(
            f"Response contains potentially unsafe content. Concerns: {', '.join(result.concerns)}",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )

    if result.confidence_score < 0.6:
        raise OutputCheckError(
            f"Response quality score too low ({result.confidence_score:.2f}). Concerns: {', '.join(result.concerns)}",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )


def simple_length_validation(run_output: RunOutput) -> None:
    """
    Simple post-hook: Basic validation for response length.

    Ensures responses are neither too short nor excessively long.
    """
    content = run_output.content.strip()

    if len(content) < 20:
        raise OutputCheckError(
            "Response is too brief to be helpful",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )

    if len(content) > 5000:
        raise OutputCheckError(
            "Response is too lengthy and may overwhelm the user",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )


async def main():
    """Demonstrate output validation post-hooks."""
    print("🔍 Output Validation Post-Hook Example")
    print("=" * 60)

    # Agent with comprehensive output validation
    agent_with_validation = Agent(
        name="Customer Support Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        post_hooks=[validate_response_quality],
        instructions=[
            "You are a helpful customer support agent.",
            "Provide clear, professional responses to customer inquiries.",
            "Be concise but thorough in your explanations.",
        ],
    )

    # Agent with simple validation only
    agent_simple = Agent(
        name="Simple Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        post_hooks=[simple_length_validation],
        instructions=[
            "You are a helpful assistant. Keep responses focused and appropriate length."
        ],
    )

    # Test 1: Good response (should pass validation)
    print("\n✅ Test 1: Well-formed response")
    print("-" * 40)
    try:
        await agent_with_validation.aprint_response(
            input="How do I reset my password on my Microsoft account?"
        )
        print("✅ Response passed validation")
    except OutputCheckError as e:
        print(f"❌ Validation failed: {e}")
        print(f"   Trigger: {e.check_trigger}")

    # Test 2: Force a short response (should fail simple validation)
    print("\n❌ Test 2: Too brief response")
    print("-" * 40)
    try:
        # Use a more constrained instruction to get a brief response
        brief_agent = Agent(
            name="Brief Agent",
            model=OpenAIChat(id="gpt-4o-mini"),
            post_hooks=[simple_length_validation],
            instructions=["Answer in 1-2 words only."],
        )
        await brief_agent.aprint_response(input="What is the capital of France?")
    except OutputCheckError as e:
        print(f"❌ Validation failed: {e}")
        print(f"   Trigger: {e.check_trigger}")

    # Test 3: Normal response with simple validation
    print("\n✅ Test 3: Normal response with simple validation")
    print("-" * 40)
    try:
        await agent_simple.aprint_response(
            input="Explain what a database is in simple terms."
        )
        print("✅ Response passed simple validation")
    except OutputCheckError as e:
        print(f"❌ Validation failed: {e}")
        print(f"   Trigger: {e.check_trigger}")


if __name__ == "__main__":
    asyncio.run(main())
