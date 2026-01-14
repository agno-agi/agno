"""
Example demonstrating how to use PII detection guardrails with Agno Team.

This example shows how to:
1. Detect and block personally identifiable information (PII) in input
2. Protect sensitive data like SSNs, credit cards, emails, and phone numbers
3. Handle different types of PII violations with appropriate error messages
"""

import asyncio

from agno.exceptions import InputCheckError
from agno.guardrails import PIIDetectionGuardrail
from agno.models.openai import OpenAIChat
from agno.team.team import Team


async def main():
    """Demonstrate PII detection guardrails functionality."""
    print("🛡️ PII Detection Guardrails Demo")
    print("=" * 50)

    # Create an team with PII detection protection
    team = Team(
        name="Privacy-Protected Team",
        members=[],
        model=OpenAIChat(id="gpt-4o-mini"),
        pre_hooks=[PIIDetectionGuardrail()],
        description="A team that helps with customer service while protecting privacy.",
        instructions="You are a helpful customer service assistant. Always protect user privacy and handle sensitive information appropriately.",
    )

    # Test 1: Normal request without PII (should work)
    print("\n✅ Test 1: Normal request without PII")
    print("-" * 30)
    try:
        team.print_response(
            input="Can you help me understand your return policy?",
        )
        print("✅ Normal request processed successfully")
    except InputCheckError as e:
        print(f"❌ Unexpected error: {e}")

    # Test 2: Request with SSN (should be blocked)
    print("\n🔴 Test 2: Input containing SSN")
    print("-" * 30)
    try:
        team.print_response(
            input="Hi, my Social Security Number is 123-45-6789. Can you help me with my account?",
        )
        print("⚠️ This should have been blocked!")
    except InputCheckError as e:
        print(f"✅ PII blocked: {e.message}")
        print(f"   Trigger: {e.check_trigger}")

    # Test 3: Request with credit card (should be blocked)
    print("\n🔴 Test 3: Input containing credit card")
    print("-" * 30)
    try:
        team.print_response(
            input="I'd like to update my payment method. My new card number is 4532 1234 5678 9012.",
        )
        print("⚠️ This should have been blocked!")
    except InputCheckError as e:
        print(f"✅ PII blocked: {e.message}")
        print(f"   Trigger: {e.check_trigger}")

    # Test 4: Request with email address (should be blocked)
    print("\n🔴 Test 4: Input containing email address")
    print("-" * 30)
    try:
        team.print_response(
            input="Please send the receipt to john.doe@example.com for my recent purchase.",
        )
        print("⚠️ This should have been blocked!")
    except InputCheckError as e:
        print(f"✅ PII blocked: {e.message}")
        print(f"   Trigger: {e.check_trigger}")

    # Test 5: Request with phone number (should be blocked)
    print("\n🔴 Test 5: Input containing phone number")
    print("-" * 30)
    try:
        team.print_response(
            input="My phone number is 555-123-4567. Please call me about my order status.",
        )
        print("⚠️ This should have been blocked!")
    except InputCheckError as e:
        print(f"✅ PII blocked: {e.message}")
        print(f"   Trigger: {e.check_trigger}")

    # Test 6: Mixed PII in context (should be blocked)
    print("\n🔴 Test 6: Multiple PII types in one request")
    print("-" * 30)
    try:
        team.print_response(
            input="Hi, I'm John Smith. My email is john@company.com and phone is 555.987.6543. I need help with my account.",
        )
        print("⚠️ This should have been blocked!")
    except InputCheckError as e:
        print(f"✅ PII blocked: {e.message}")
        print(f"   Trigger: {e.check_trigger}")

    # Test 7: Edge case - formatted differently (should still be blocked)
    print("\n🔴 Test 7: PII with different formatting")
    print("-" * 30)
    try:
        team.print_response(
            input="Can you verify my credit card ending in 4532123456789012?",
        )
        print("⚠️ This should have been blocked!")
    except InputCheckError as e:
        print(f"✅ PII blocked: {e.message}")
        print(f"   Trigger: {e.check_trigger}")

    # Create an team with PII detection which masks the PII in the input
    team = Team(
        name="Privacy-Protected Team",
        members=[],
        model=OpenAIChat(id="gpt-4o-mini"),
        pre_hooks=[PIIDetectionGuardrail(mask_pii=True)],
        description="A team that helps with customer service while protecting privacy.",
        instructions="You are a helpful customer service assistant. Always protect user privacy and handle sensitive information appropriately.",
    )

    # Test 8: Request with SSN (should be masked)
    print("\n🔴 Test 8: Input containing SSN")
    print("-" * 30)
    team.print_response(
        input="Hi, my Social Security Number is 123-45-6789. Can you help me with my account?",
    )


if __name__ == "__main__":
    asyncio.run(main())
