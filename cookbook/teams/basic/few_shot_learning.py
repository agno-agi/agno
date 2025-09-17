"""
This example shows a straightforward use case of additional_input
to teach a customer support team proper response patterns.
"""

from agno.agent import Agent
from agno.models.message import Message
from agno.models.openai.chat import OpenAIChat
from agno.team import Team

# Few-shot examples showing good support patterns
support_examples = [
    # Example 1: Simple issue resolution
    Message(role="user", content="I forgot my password and can't log in"),
    Message(
        role="assistant",
        content="""
    I'll help you reset your password right away.
    
    **Transferring to Support Specialist**: Please assist this customer with password reset:
    - Guide them through the password reset process
    - Verify their identity if needed  
    - Ensure they can successfully log in
    - Provide tips for creating a secure password
    
    Expected outcome: Customer successfully logs in with new password.
    """.strip(),
    ),
    # Example 2: Escalation pattern
    Message(
        role="user",
        content="I've been charged twice for the same order and your chat bot couldn't help!",
    ),
    Message(
        role="assistant",
        content="""
        I sincerely apologize for the billing issue and the frustration with our chat system.

        **Transferring to Escalation Manager**: Priority billing issue requiring immediate attention:
        - Customer charged twice for same order
        - Previous automated support was unsuccessful
        - Customer is understandably frustrated
        - Needs immediate resolution and possible compensation

        Expected outcome: Billing corrected, customer satisfaction restored, and follow-up to prevent recurrence.
        """.strip(),
    ),
    # Example 3: Proactive support
    Message(role="user", content="Your app keeps crashing when I try to upload photos"),
    Message(
        role="assistant",
        content="""
    I'm sorry you're experiencing crashes with photo uploads. Let me get this resolved for you. 

    **Transferring to Support Specialist**: Technical issue with photo upload feature:
    - App crashes during photo upload process
    - Need to troubleshoot device compatibility and app version
    - Provide workaround solutions if available
    - Escalate to technical team if it's a known bug    

    Expected outcome: Upload feature working properly or clear timeline for fix provided.
        """.strip(),
    ),
]

if __name__ == "__main__":
    # Support Agent
    support_agent = Agent(
        name="Support Specialist",
        role="Handle customer inquiries",
        model=OpenAIChat(id="o3-mini"),
        instructions=[
            "You are a helpful customer support specialist.",
            "Always be polite, professional, and solution-oriented.",
        ],
    )

    # Escalation Agent
    escalation_agent = Agent(
        name="Escalation Manager",
        role="Handle complex issues",
        model=OpenAIChat(id="o3-mini"),
        instructions=[
            "You handle escalated customer issues that require management attention.",
            "Focus on customer satisfaction and finding solutions.",
        ],
    )

    # Create team with few-shot learning
    team = Team(
        name="Customer Support Team",
        members=[support_agent, escalation_agent],
        model=OpenAIChat(id="o3-mini"),
        add_name_to_context=True,
        additional_input=support_examples,  # 🆕 Teaching examples
        instructions=[
            "You coordinate customer support with excellence and empathy.",
            "Follow established patterns for proper issue resolution.",
            "Always prioritize customer satisfaction and clear communication.",
        ],
        markdown=True,
    )

    scenarios = [
        "I can't find my order confirmation email",
        "The product I received is damaged",
        "I want to cancel my subscription but the website won't let me",
    ]

    for i, scenario in enumerate(scenarios, 1):
        print(f"📞 Scenario {i}: {scenario}")
        print("-" * 50)
        team.print_response(scenario)
