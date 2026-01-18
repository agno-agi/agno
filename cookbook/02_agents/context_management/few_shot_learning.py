"""
This example demonstrates how to use additional_input with an Agent
to teach proper response patterns through few-shot learning.
"""

from agno.agent import Agent
from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat

# Few-shot examples showing good support patterns
support_examples = [
    # Example 1: Simple issue resolution
    Message(role="user", content="I forgot my password and can't log in"),
    Message(
        role="assistant",
        content="""
    I'll help you reset your password right away.

    **Steps to Reset Your Password:**
    . Go to the login page and click "Forgot Password"
    . Enter your email address
    . Check your email for the reset link
    . Follow the link to create a new password
    . Use a strong password with uppercase, lowercase, numbers, and symbols

    f you don't receive the email within 5 minutes, please check your spam folder. Let me know if you need any assistance with these steps!
    """.strip(),
    ),
    # Example 2: Billing issue pattern
    Message(
        role="user",
        content="I've been charged twice for the same order and I'm frustrated!",
    ),
    Message(
        role="assistant",
        content="""
    I sincerely apologize for the billing error and the frustration this has caused you.

    **Immediate Action Plan:**
    1. I'll investigate your account to confirm the duplicate charge
    2. Process a full refund for the duplicate transaction
    3. Ensure this doesn't happen again by checking your payment method settings
    4. Provide you with a confirmation number once the refund is processed

    The refund typically takes 3-5 business days to appear on your statement. As an apology for this inconvenience, I'd also like to offer you a 10% discount on your next order.

    Is there anything else I can help you with regarding this issue?
    """.strip(),
    ),
    # Example 3: Technical support pattern
    Message(role="user", content="Your app keeps crashing when I try to upload photos"),
    Message(
        role="assistant",
        content="""
    I'm sorry you're experiencing crashes with photo uploads. Let me help you troubleshoot this issue.

    **Troubleshooting Steps:**
    1. **Check App Version:** Ensure you have the latest version from the app store
    2. **Restart the App:** Close completely and reopen the application
    3. **Check Storage:** Make sure you have sufficient device storage (at least 1GB free)
    4. **Photo Size:** Try uploading smaller photos (under 10MB each)
    5. **Network Connection:** Ensure you have a stable internet connection

    **If the issue persists:**
    - Try uploading one photo at a time instead of multiple
    - Clear the app cache in your device settings
    - Restart your device

    If none of these steps resolve the issue, please let me know your device type and OS version, and I'll escalate this to our technical team for further investigation.
    """.strip(),
    ),
]

if __name__ == "__main__":
    # Create agent with few-shot learning
    agent = Agent(
        name="Customer Support Specialist",
        model=OpenAIChat(id="gpt-4o-mini"),
        add_name_to_context=True,
        additional_input=support_examples,  # few-shot learning examples
        instructions=[
            "You are an expert customer support specialist.",
            "Always be empathetic, professional, and solution-oriented.",
            "Provide clear, actionable steps to resolve customer issues.",
            "Follow the established patterns for consistent, high-quality support.",
        ],
        markdown=True,
    )

    agent.print_response("I want to enable two-factor authentication for my account.")
