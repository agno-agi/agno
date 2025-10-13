"""Customer Support AI Team - Multi-agent team for intelligent customer support"""

from textwrap import dedent

from agno.agent import Agent
from agno.exceptions import CheckTrigger, InputCheckError
from agno.models.openai.chat import OpenAIChat
from agno.run.team import TeamRunInput
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from pydantic import BaseModel, Field

from agno.db.sqlite.sqlite import SqliteDb

db = SqliteDb(id="real-world-db", db_file="tmp/real_world.db")


class SupportTicket(BaseModel):
    """Structured support ticket classification"""

    category: str = Field(description="Category: technical, billing, product, account")
    priority: str = Field(description="Priority: low, medium, high, critical")
    sentiment: str = Field(description="Customer sentiment: positive, neutral, negative, angry")
    requires_escalation: bool = Field(description="Whether ticket needs human escalation")
    estimated_resolution_time: str = Field(description="Estimated time to resolve")
    suggested_actions: list[str] = Field(description="List of recommended actions")


def validate_support_input(run_input: TeamRunInput, team: Team) -> None:
    """Pre-hook: Validate support tickets contain sufficient information"""
    user_message = run_input.input_content.lower()

    if len(user_message.strip()) < 10:
        raise InputCheckError(
            "Support tickets must contain at least 10 characters with sufficient detail.",
            check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
        )

    # Block spam or abuse
    spam_keywords = ["test", "hello", "hi there", "asdf"]
    if any(keyword in user_message for keyword in spam_keywords) and len(user_message) < 20:
        raise InputCheckError(
            "Please provide a detailed description of your support issue.",
            check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
        )


ticket_classifier = Agent(
    name="Ticket Classifier",
    role="Analyzes and classifies incoming support tickets",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Expert at analyzing customer support requests and classifying them by category, priority, and sentiment",
    instructions=[
        "Analyze customer support tickets thoroughly",
        "Classify by category: technical, billing, product, or account",
        "Assess priority based on urgency and impact",
        "Detect customer sentiment and emotional state",
        "Identify if human escalation is needed",
        "Provide estimated resolution time",
        "Suggest immediate actions for resolution",
        "Remember past ticket patterns and customer history",
    ],
    enable_user_memories=True,
    add_history_to_context=True,
    num_history_runs=5,
    add_datetime_to_context=True,
    db=db,
    output_schema=SupportTicket,
    markdown=True,
)

support_resolver = Agent(
    name="Support Resolver",
    role="Provides solutions and resolutions for support tickets",
    model=OpenAIChat(id="gpt-4o"),
    description="Expert support agent with deep product knowledge and problem-solving skills",
    instructions=[
        "Provide clear, actionable solutions to customer problems",
        "Use empathetic and professional language",
        "Break down complex solutions into simple steps",
        "Offer alternative solutions when possible",
        "Include relevant documentation links and resources",
        "Follow up with preventive measures",
        "Remember past solutions and customer preferences",
        "Track successful resolutions for similar issues",
    ],
    tools=[DuckDuckGoTools()],
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=10,
    add_datetime_to_context=True,
    db=db,
    markdown=True,
)

escalation_manager = Agent(
    name="Escalation Manager",
    role="Manages ticket escalation and prioritization",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Specialist in managing critical issues and escalation workflows",
    instructions=[
        "Review ticket classification and resolution",
        "Determine if escalation to human agent is necessary",
        "Provide escalation reasoning and priority justification",
        "Summarize the issue for handoff to human agents",
        "Track recurring issues for pattern analysis",
        "Remember escalation patterns and customer history",
        "Identify customers with multiple escalations",
    ],
    enable_user_memories=True,
    enable_session_summaries=True,
    add_history_to_context=True,
    num_history_runs=8,
    add_datetime_to_context=True,
    db=db,
    markdown=True,
)

customer_support_team = Team(
    id="customer-support-team",
    name="Customer Support AI Team",
    session_id="customer_support_session",
    model=OpenAIChat(id="gpt-4o"),
    members=[ticket_classifier, support_resolver, escalation_manager],
    db=db,
    pre_hooks=[validate_support_input],
    description=dedent("""\
        Intelligent customer support system with automated ticket classification,
        resolution, and escalation management. Features comprehensive memory to track
        customer history, past tickets, resolutions, and preferences across all interactions.\
    """),
    instructions=[
        "First, use the Ticket Classifier to analyze and categorize the support request",
        "Then, use the Support Resolver to provide a comprehensive solution",
        "Finally, use the Escalation Manager to review and determine if human escalation is needed",
        "Maintain empathetic and professional communication throughout",
        "Remember customer context from ALL previous interactions",
        "Reference past tickets and resolutions for faster problem-solving",
        "Track customer satisfaction and recurring issues",
        "Provide clear, actionable solutions with step-by-step guidance",
    ],
    show_members_responses=True,
    markdown=True,
)
