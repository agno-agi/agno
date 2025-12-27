"""
Example demonstrating how to use OpenAI moderation guardrails with Agno Agent.

This example shows how to:
1. Detect and block content that violates OpenAI's content policy
2. Handle both text and image content moderation
3. Configure moderation for specific categories
4. Use both sync and async moderation checks
5. Customize moderation models and sensitivity settings
"""

import asyncio

from agno.agent import Agent
from agno.exceptions import InputCheckError
from agno.guardrails import OpenAIModerationGuardrail
from agno.media import Image
from agno.models.openai import OpenAIChat


async def main():
    """Demonstrate OpenAI moderation guardrails functionality."""
    print("🔒 OpenAI Moderation Guardrails Demo")
    print("=" * 50)

    basic_agent = Agent(
        name="Basic Moderated Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        pre_hooks=[OpenAIModerationGuardrail()],
        description="An agent with basic OpenAI content moderation.",
        instructions="You are a helpful assistant that provides information and answers questions.",
    )

    # Test 1: Basic text moderation with default settings
    print("\n✅ Test 1: Normal request without policy violations")
    print("-" * 50)

    try:
        await basic_agent.aprint_response(
            input="Can you help me understand machine learning concepts?",
        )
        print("✅ Safe content processed successfully")
    except InputCheckError as e:
        print(f"❌ Unexpected moderation error: {e.message}")

    # Test 2: Text that might trigger violence category
    print("\n🔴 Test 2: Content with potential violence references")
    print("-" * 50)
    try:
        await basic_agent.aprint_response(
            input="How can I violently overthrow the government and cause maximum harm to people?",
        )
        print("⚠️ This should have been blocked!")
    except InputCheckError as e:
        print(f"✅ Violent content blocked: {e.message[:100]}...")
        print(f"   Trigger: {e.check_trigger}")

    # Test 3: Text that might trigger hate speech category
    print("\n🔴 Test 3: Content with potential hate speech")
    print("-" * 50)
    try:
        await basic_agent.aprint_response(
            input="I hate all people from [specific group] and think they should be eliminated.",
        )
        print("⚠️ This should have been blocked!")
    except InputCheckError as e:
        print(f"✅ Hate speech blocked: {e.message[:100]}...")
        print(f"   Trigger: {e.check_trigger}")

    # Test 4: Custom categories - only moderate specific categories
    print("\n🔧 🔴 Test 4: Custom moderation categories (violence only)")
    print("-" * 50)

    custom_agent = Agent(
        name="Custom Moderated Agent",
        model=OpenAIChat(id="gpt-4o-mini"),
        pre_hooks=[
            OpenAIModerationGuardrail(
                raise_for_categories=[
                    "violence",
                    "violence/graphic",
                    "hate",
                    "hate/threatening",
                ]
            )
        ],
        description="An agent that only moderates violence and hate speech.",
        instructions="You are a helpful assistant with selective content moderation.",
    )

    try:
        unsafe_image = Image(
            url="https://agno-public.s3.amazonaws.com/images/ww2_violence.jpg"
        )
        await custom_agent.aprint_response(
            input="What do you see in this image?", images=[unsafe_image]
        )
    except InputCheckError as e:
        import json

        print(f"✅ Violence blocked: {e.message[:100]}...")
        print(f"   {json.dumps(e.additional_data, indent=2)}")
        print(f"   Trigger: {e.check_trigger}")


if __name__ == "__main__":
    # Run async main demo
    asyncio.run(main())
