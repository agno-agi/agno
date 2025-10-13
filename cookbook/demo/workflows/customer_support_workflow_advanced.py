"""
Advanced Customer Support Workflow - Intelligent ticket routing and resolution

This workflow demonstrates:
- Router for ticket type classification and routing to specialists
- Parallel knowledge base search + past ticket analysis
- Conditional escalation based on severity
- Loop for solution validation
- Early stopping for critical/emergency tickets
"""

from textwrap import dedent
from typing import List

from agno.agent import Agent
from agno.models.openai.chat import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.workflow.condition import Condition
from agno.workflow.loop import Loop
from agno.workflow.parallel import Parallel
from agno.workflow.router import Router
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput
from agno.workflow.workflow import Workflow
from pydantic import BaseModel, Field

from agno.db.sqlite.sqlite import SqliteDb

db = SqliteDb(id="real-world-db", db_file="tmp/real_world.db")

# ============================================================================
# Data Models
# ============================================================================


class TicketClassification(BaseModel):
    """Structured ticket classification"""

    category: str = Field(description="Category: technical, billing, product, account, emergency")
    priority: str = Field(description="Priority: low, medium, high, critical")
    sentiment: str = Field(description="Customer sentiment: positive, neutral, negative, angry")
    requires_human_escalation: bool = Field(description="Whether ticket needs human escalation")


# ============================================================================
# Specialist Agents
# ============================================================================

ticket_classifier = Agent(
    name="Ticket Classifier",
    role="Classifies support tickets",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Expert at analyzing and classifying customer support tickets",
    instructions=[
        "Analyze the support ticket thoroughly",
        "Classify by category: technical, billing, product, account, or emergency",
        "Assess priority: low, medium, high, or critical",
        "Detect customer sentiment",
        "Identify if human escalation is needed",
        "Extract key information and context",
    ],
    output_schema=TicketClassification,
    db=db,
    markdown=True,
)

technical_specialist = Agent(
    name="Technical Support Specialist",
    role="Resolves technical issues",
    model=OpenAIChat(id="gpt-4o"),
    description="Expert technical support agent for troubleshooting",
    instructions=[
        "Provide clear technical solutions",
        "Break down complex steps",
        "Include troubleshooting guides",
        "Reference documentation",
        "Offer alternative approaches",
    ],
    tools=[DuckDuckGoTools()],
    db=db,
    markdown=True,
)

billing_specialist = Agent(
    name="Billing Support Specialist",
    role="Resolves billing and payment issues",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Expert in billing, payments, and subscription management",
    instructions=[
        "Handle billing inquiries professionally",
        "Explain charges clearly",
        "Provide refund/adjustment policies",
        "Offer payment plan options",
        "Be empathetic with billing concerns",
    ],
    db=db,
    markdown=True,
)

product_specialist = Agent(
    name="Product Support Specialist",
    role="Handles product questions and feature requests",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Product expert who helps with features and usage",
    instructions=[
        "Explain product features clearly",
        "Provide usage best practices",
        "Share tips and tricks",
        "Collect feature feedback",
        "Guide users to relevant resources",
    ],
    db=db,
    markdown=True,
)

account_specialist = Agent(
    name="Account Support Specialist",
    role="Manages account-related issues",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Expert in account management and security",
    instructions=[
        "Handle account security issues",
        "Assist with password resets",
        "Manage profile updates",
        "Address privacy concerns",
        "Guide through account recovery",
    ],
    db=db,
    markdown=True,
)

knowledge_base_agent = Agent(
    name="Knowledge Base Search",
    role="Searches knowledge base for solutions",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Searches internal knowledge base for relevant solutions",
    instructions=[
        "Search for similar issues in knowledge base",
        "Find relevant documentation",
        "Identify proven solutions",
        "Extract key troubleshooting steps",
    ],
    tools=[DuckDuckGoTools()],  # Replace with actual KB tool
    db=db,
    markdown=True,
)

past_ticket_analyzer = Agent(
    name="Past Ticket Analyzer",
    role="Analyzes similar past tickets",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Analyzes past tickets for patterns and solutions",
    instructions=[
        "Search for similar past tickets",
        "Identify successful resolutions",
        "Note recurring issues",
        "Extract applicable solutions",
    ],
    db=db,
    markdown=True,
)

solution_validator = Agent(
    name="Solution Validator",
    role="Validates and improves solutions",
    model=OpenAIChat(id="gpt-4o"),
    description="Reviews solutions for quality and completeness",
    instructions=[
        "Review solution for completeness",
        "Check for accuracy",
        "Ensure clarity and professionalism",
        "Verify actionable steps are provided",
        "Rate solution quality (1-10)",
    ],
    db=db,
    markdown=True,
)

escalation_manager = Agent(
    name="Escalation Manager",
    role="Manages ticket escalation",
    model=OpenAIChat(id="gpt-4o-mini"),
    description="Handles critical issues and escalation workflows",
    instructions=[
        "Review ticket severity",
        "Determine escalation necessity",
        "Prepare escalation summary",
        "Assign priority and urgency",
        "Provide handoff notes for human agents",
    ],
    db=db,
    markdown=True,
)

# ============================================================================
# Workflow Steps
# ============================================================================

# Classification
classification_step = Step(
    name="ClassifyTicket",
    description="Classify and analyze support ticket",
    agent=ticket_classifier,
)

# Parallel context gathering
knowledge_base_step = Step(
    name="SearchKnowledgeBase",
    description="Search knowledge base for solutions",
    agent=knowledge_base_agent,
)

past_tickets_step = Step(
    name="AnalyzePastTickets",
    description="Analyze similar past tickets",
    agent=past_ticket_analyzer,
)

# Specialist resolution steps (router choices)
technical_resolution_step = Step(
    name="TechnicalResolution",
    description="Resolve technical issue",
    agent=technical_specialist,
)

billing_resolution_step = Step(
    name="BillingResolution",
    description="Resolve billing issue",
    agent=billing_specialist,
)

product_resolution_step = Step(
    name="ProductResolution",
    description="Handle product inquiry",
    agent=product_specialist,
)

account_resolution_step = Step(
    name="AccountResolution",
    description="Resolve account issue",
    agent=account_specialist,
)

# Validation and escalation
validation_step = Step(
    name="ValidateSolution",
    description="Validate solution quality",
    agent=solution_validator,
)

escalation_step = Step(
    name="EscalateTicket",
    description="Escalate ticket to human agent",
    agent=escalation_manager,
)


# ============================================================================
# Custom Functions for Workflow Logic
# ============================================================================


def emergency_check(step_input: StepInput) -> StepOutput:
    """Check for emergency/critical issues that need immediate escalation"""
    ticket = (step_input.input or "").lower()

    # Emergency keywords
    emergency_keywords = [
        "security breach",
        "data loss",
        "service down",
        "critical",
        "urgent",
        "emergency",
        "cannot access",
        "production down",
        "payment failed",
        "account locked",
    ]

    is_emergency = any(keyword in ticket for keyword in emergency_keywords)

    if is_emergency:
        print(f"🚨 EMERGENCY DETECTED: Immediate escalation required")
        return StepOutput(
            content=dedent(f"""\
                🚨 CRITICAL ISSUE DETECTED

                Ticket: {ticket[:200]}...

                This issue has been flagged for immediate human attention due to:
                - Potential service impact
                - Security concerns
                - Critical business operation

                A senior support specialist will be assigned immediately.
            """),
            stop=True,  # Stop workflow and escalate immediately
        )

    print(f"✅ No emergency detected. Proceeding with normal workflow.")
    return StepOutput(content=ticket, stop=False)


def ticket_router(step_input: StepInput) -> List[Step]:
    """Route ticket to appropriate specialist based on classification"""
    # Get classification from previous step
    previous_content = step_input.previous_step_content or ""
    ticket = step_input.input or ""

    # Combine both for analysis
    full_context = f"{ticket} {previous_content}".lower()

    # Route based on category
    if any(keyword in full_context for keyword in ["technical", "error", "bug", "not working", "crash"]):
        print(f"🔧 Routing to Technical Specialist")
        return [technical_resolution_step]
    elif any(keyword in full_context for keyword in ["billing", "payment", "refund", "charge", "invoice"]):
        print(f"💳 Routing to Billing Specialist")
        return [billing_resolution_step]
    elif any(keyword in full_context for keyword in ["feature", "how to", "product", "functionality"]):
        print(f"📦 Routing to Product Specialist")
        return [product_resolution_step]
    elif any(keyword in full_context for keyword in ["account", "password", "login", "profile", "security"]):
        print(f"👤 Routing to Account Specialist")
        return [account_resolution_step]
    else:
        print(f"🔧 Routing to Technical Specialist (default)")
        return [technical_resolution_step]


def should_escalate(step_input: StepInput) -> bool:
    """Determine if ticket needs human escalation"""
    content = (step_input.get_all_previous_content() or "").lower()

    # Escalation triggers
    escalation_triggers = [
        "angry",
        "frustrated",
        "legal",
        "lawsuit",
        "refund",
        "cancel account",
        "speak to manager",
        "critical",
        "high priority",
        "requires_human_escalation: true",
    ]

    needs_escalation = any(trigger in content for trigger in escalation_triggers)

    print(f"🎯 Human escalation needed: {needs_escalation}")
    return needs_escalation


def solution_quality_check(outputs: List[StepOutput]) -> bool:
    """Check if solution meets quality standards"""
    if not outputs:
        return False

    last_content = str(outputs[-1].content or "").lower()

    # Quality indicators
    has_steps = any(marker in last_content for marker in ["step 1", "1.", "first", "next"])
    has_length = len(last_content) > 200
    has_quality_score = any(score in last_content for score in ["8/10", "9/10", "10/10", "8.", "9.", "10."])

    should_continue = not (has_steps and has_length and has_quality_score)

    if should_continue:
        print(f"🔄 Solution quality check: Needs improvement. Continuing loop...")
    else:
        print(f"✅ Solution quality check: Meets standards. Ending loop.")

    # Return True to STOP the loop
    return not should_continue


# ============================================================================
# Main Workflow
# ============================================================================

customer_support_workflow = Workflow(
    name="Intelligent Customer Support Workflow",
    description=dedent("""\
        Advanced customer support workflow with intelligent routing and quality control.

        Features:
        - Emergency detection with immediate escalation
        - Ticket classification and analysis
        - Parallel knowledge base and past ticket search
        - Smart routing to specialized support agents
        - Quality-driven solution validation loop
        - Conditional human escalation
    """),
    steps=[
        # Phase 1: Emergency Check (Early Stopping)
        Step(
            name="EmergencyCheck",
            executor=emergency_check,
            description="Check for emergency issues requiring immediate escalation",
        ),
        # Phase 2: Classification
        classification_step,
        # Phase 3: Context Gathering (Parallel)
        Parallel(
            knowledge_base_step,
            past_tickets_step,
            name="ContextGathering",
            description="Gather context from knowledge base and past tickets",
        ),
        # Phase 4: Specialist Routing
        Router(
            name="SpecialistRouter",
            selector=ticket_router,
            choices=[
                technical_resolution_step,
                billing_resolution_step,
                product_resolution_step,
                account_resolution_step,
            ],
            description="Route to appropriate specialist",
        ),
        # Phase 5: Solution Validation Loop
        Loop(
            name="SolutionValidationLoop",
            steps=[validation_step],
            end_condition=solution_quality_check,
            max_iterations=2,
            description="Validate and improve solution until quality standards met",
        ),
        # Phase 6: Conditional Escalation
        Condition(
            name="HumanEscalation",
            evaluator=should_escalate,
            steps=[escalation_step],
            description="Escalate to human agent if needed",
        ),
    ],
    db=db,
    store_events=True,
    markdown=True,
)


# ============================================================================
# Usage Examples
# ============================================================================

if __name__ == "__main__":
    # Example 1: Technical issue
    print("\n" + "=" * 80)
    print("Example 1: Technical Issue")
    print("=" * 80)
    customer_support_workflow.print_response(
        "My application crashes every time I try to export data. Getting error code 500.",
        stream=True,
        stream_intermediate_steps=True,
    )

    # Example 2: Billing inquiry
    print("\n" + "=" * 80)
    print("Example 2: Billing Issue")
    print("=" * 80)
    customer_support_workflow.print_response(
        "I was charged twice for my monthly subscription. Need a refund for the duplicate charge.",
        stream=True,
        stream_intermediate_steps=True,
    )

    # Example 3: Emergency (should trigger immediate escalation)
    print("\n" + "=" * 80)
    print("Example 3: Emergency Issue")
    print("=" * 80)
    customer_support_workflow.print_response(
        "URGENT: Our production service is down and customers cannot access their accounts!",
        stream=True,
        stream_intermediate_steps=True,
    )
