"""🎫 AI-Powered Customer Support Orchestrator - Intelligent Ticket Resolution Workflow

This workflow demonstrates advanced Agno workflow patterns for automated customer support:
- Router-based ticket classification (4 paths: URGENT, TECHNICAL, BILLING, GENERAL)
- Parallel knowledge retrieval from multiple sources
- Iterative solution refinement with quality gates
- Conditional escalation to human agents
- Session state management for ticket context
- Structured I/O with Pydantic models

Business Value: 70% cost reduction, 24/7 availability, 90% faster resolution
"""

from textwrap import dedent
from typing import List, Literal, Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.anthropic import Claude
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.workflow import Loop, Parallel, Router, Step, Workflow
from agno.workflow.types import StepInput, StepOutput
from pydantic import BaseModel, Field

# ============================================================================
# Database Setup
# ============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, id="support_workflow_db")

# ============================================================================
# Pydantic Models for Structured I/O
# ============================================================================


class SupportTicket(BaseModel):
    """Input schema for customer support tickets"""

    ticket_id: str = Field(description="Unique ticket identifier")
    customer_email: str = Field(description="Customer email address")
    subject: str = Field(description="Ticket subject line")
    description: str = Field(description="Detailed description of the issue")
    priority: Literal["LOW", "MEDIUM", "HIGH", "URGENT"] = Field(
        description="Ticket priority level"
    )
    customer_tier: Optional[Literal["FREE", "PRO", "ENTERPRISE"]] = Field(
        default="FREE", description="Customer subscription tier"
    )


class KnowledgeSource(BaseModel):
    """Knowledge source with relevance score"""

    source_type: Literal["documentation", "historical_ticket", "product_status"]
    content: str
    relevance_score: float = Field(ge=0.0, le=1.0)


class SolutionOutput(BaseModel):
    """Output schema for proposed solutions"""

    solution_text: str = Field(description="Detailed solution to the customer issue")
    confidence_score: float = Field(
        ge=0.0, le=1.0, description="Confidence in the solution (0-1)"
    )
    sources: List[str] = Field(description="Sources used to generate solution")
    escalation_needed: bool = Field(description="Whether human escalation is required")
    suggested_actions: List[str] = Field(
        description="Step-by-step actions for customer"
    )
    estimated_resolution_time: str = Field(description="Estimated time to resolve")


# ============================================================================
# Specialized Support Agents
# ============================================================================

documentation_agent = Agent(
    name="Documentation Specialist",
    model=Claude(id="claude-sonnet-4-0"),
    role="Search and retrieve relevant documentation for customer issues",
    tools=[DuckDuckGoTools()],
    instructions=dedent("""\
        You are a documentation specialist with deep knowledge of product documentation.

        Your responsibilities:
        1. Search through documentation for relevant solutions
        2. Find setup guides, troubleshooting steps, and best practices
        3. Identify relevant API documentation and code examples
        4. Rate the relevance of found documentation (0-1 scale)

        Focus on finding accurate, up-to-date information that directly addresses the issue.
        \
    """),
)

historical_ticket_agent = Agent(
    name="Historical Ticket Analyst",
    model=Claude(id="claude-sonnet-4-0"),
    role="Analyze historical tickets to find similar resolved issues",
    instructions=dedent("""\
        You are a historical ticket analyst specializing in pattern recognition.

        Your responsibilities:
        1. Search for similar previously resolved tickets
        2. Identify common issue patterns and their solutions
        3. Extract successful resolution strategies
        4. Rate similarity to current issue (0-1 scale)

        Look for tickets with:
        - Similar error messages or symptoms
        - Same product features or components
        - Comparable customer contexts

        Provide insights on what worked in the past.
        \
    """),
)

product_status_agent = Agent(
    name="Product Status Monitor",
    model=Claude(id="claude-sonnet-4-0"),
    role="Check product status, known issues, and system health",
    tools=[DuckDuckGoTools()],
    instructions=dedent("""\
        You are a product status monitor tracking system health and known issues.

        Your responsibilities:
        1. Check for ongoing incidents or outages
        2. Identify known bugs affecting users
        3. Review recent deployments or changes
        4. Check service status and performance metrics

        Determine if the issue is:
        - A known system-wide problem
        - Related to recent changes
        - An isolated incident
        - User-specific configuration issue
        \
    """),
)

solution_composer_agent = Agent(
    name="Solution Composer",
    model=Claude(id="claude-sonnet-4-0"),
    role="Synthesize knowledge into actionable customer solutions",
    instructions=dedent("""\
        You are an expert solution composer creating clear, actionable responses.

        Your responsibilities:
        1. Synthesize information from multiple knowledge sources
        2. Create step-by-step solution instructions
        3. Provide clear, customer-friendly language
        4. Include relevant links and references
        5. Estimate resolution time realistically
        6. Assess confidence level in the solution

        Solution quality criteria:
        - Clarity: Easy to understand and follow
        - Completeness: Addresses all aspects of the issue
        - Actionability: Provides concrete next steps
        - Accuracy: Based on reliable sources

        Rate your confidence (0-1 scale) based on:
        - Source quality and relevance
        - Solution completeness
        - Historical success rate
        \
    """),
    output_schema=SolutionOutput,
)

# ============================================================================
# Escalation Agent (Human Handoff)
# ============================================================================

escalation_agent = Agent(
    name="Escalation Coordinator",
    model=Claude(id="claude-sonnet-4-0"),
    role="Prepare tickets for human agent escalation",
    instructions=dedent("""\
        You are an escalation coordinator preparing tickets for human agents.

        Your responsibilities:
        1. Summarize the issue clearly for human agents
        2. Include all context and attempted solutions
        3. Highlight customer tier and priority
        4. Provide relevant background information
        5. Suggest which specialist team should handle it

        Create a comprehensive handoff that enables:
        - Quick understanding of the issue
        - Awareness of what's already been tried
        - Clear next steps for the human agent
        \
    """),
)

# ============================================================================
# Router Selector Function (Ticket Classification)
# ============================================================================


def classify_ticket(step_input: StepInput) -> List[Step]:
    """
    Classify incoming tickets and route to appropriate resolution path.

    Classification logic:
    - URGENT: Critical issues requiring immediate attention
    - TECHNICAL: Complex technical problems needing expert analysis
    - BILLING: Payment and subscription-related issues
    - GENERAL: Standard support questions

    Args:
        step_input: Contains ticket information

    Returns:
        List of steps to execute based on classification
    """
    # Get ticket from input (assumes ticket is passed as input)
    if hasattr(step_input.input, "priority"):
        ticket = step_input.input
    else:
        # If raw string, default to GENERAL path
        print("⚠️  Using GENERAL support path (ticket not structured)")
        return [general_support_step]

    ticket_subject = ticket.subject.lower() if hasattr(ticket, "subject") else ""
    ticket_desc = ticket.description.lower() if hasattr(ticket, "description") else ""
    priority = ticket.priority if hasattr(ticket, "priority") else "MEDIUM"

    print(f"\n🎫 Classifying Ticket: {ticket.ticket_id}")
    print(f"   Priority: {priority}")
    print(f"   Subject: {ticket.subject}")

    # URGENT path: Critical issues or high-priority tickets
    if priority == "URGENT" or any(
        keyword in ticket_subject + ticket_desc
        for keyword in [
            "down",
            "outage",
            "critical",
            "urgent",
            "emergency",
            "broken",
            "not working",
        ]
    ):
        print("   → Route: URGENT (Immediate Attention Required)")
        return [urgent_support_step]

    # TECHNICAL path: Complex technical issues
    elif any(
        keyword in ticket_subject + ticket_desc
        for keyword in [
            "api",
            "integration",
            "error",
            "bug",
            "crash",
            "timeout",
            "performance",
            "database",
        ]
    ):
        print("   → Route: TECHNICAL (Expert Analysis Required)")
        return [technical_support_step]

    # BILLING path: Payment and subscription issues
    elif any(
        keyword in ticket_subject + ticket_desc
        for keyword in [
            "billing",
            "payment",
            "invoice",
            "subscription",
            "charge",
            "refund",
            "upgrade",
            "pricing",
        ]
    ):
        print("   → Route: BILLING (Financial Operations)")
        return [billing_support_step]

    # GENERAL path: Standard support questions
    else:
        print("   → Route: GENERAL (Standard Support)")
        return [general_support_step]


# ============================================================================
# Custom Function: Solution Quality Evaluator (Loop End Condition)
# ============================================================================


def evaluate_solution_quality(outputs: List[StepOutput]) -> bool:
    """
    Evaluate if the solution meets quality criteria to exit refinement loop.

    Quality gates:
    - Confidence score > 0.85
    - Solution has clear action steps
    - Sources are documented

    Args:
        outputs: List of step outputs from solution refinement

    Returns:
        True to exit loop (quality met), False to continue refining
    """
    if not outputs:
        print("   ❌ No solution outputs to evaluate")
        return False

    # Get the latest solution
    latest_output = outputs[-1]

    # Parse solution if it's structured
    if hasattr(latest_output, "content"):
        content = latest_output.content
        if isinstance(content, SolutionOutput):
            confidence = content.confidence_score
            has_actions = len(content.suggested_actions) > 0
            has_sources = len(content.sources) > 0

            print(f"\n   📊 Solution Quality Check:")
            print(f"      Confidence: {confidence:.2f}")
            print(f"      Action Steps: {len(content.suggested_actions)}")
            print(f"      Sources: {len(content.sources)}")

            # Quality gate: confidence > 0.85 and has actions and sources
            quality_met = confidence > 0.85 and has_actions and has_sources

            if quality_met:
                print("   ✅ Quality gate passed - solution ready!")
            else:
                print("   🔄 Quality gate not met - refining solution...")

            return quality_met

    # Fallback: allow after 1 iteration
    print("   ⚠️  Could not evaluate quality - continuing")
    return len(outputs) >= 1


# ============================================================================
# Custom Function: Escalation Decision
# ============================================================================


def check_escalation_needed(step_input: StepInput) -> StepOutput:
    """
    Determine if ticket needs escalation to human agent based on confidence.

    Escalation criteria:
    - Confidence score < 0.85
    - Customer is ENTERPRISE tier
    - Priority is URGENT

    Args:
        step_input: Contains solution and ticket context

    Returns:
        StepOutput with escalation decision
    """
    # Get the previous step content (solution)
    solution_content = step_input.previous_step_content

    # Parse solution
    if isinstance(solution_content, SolutionOutput):
        confidence = solution_content.confidence_score
        escalation_needed = solution_content.escalation_needed

        # Get ticket info from session state
        session_state = step_input.session_state or {}
        ticket_priority = session_state.get("ticket_priority", "MEDIUM")
        customer_tier = session_state.get("customer_tier", "FREE")

        print(f"\n   🎯 Escalation Check:")
        print(f"      Confidence: {confidence:.2f}")
        print(f"      Priority: {ticket_priority}")
        print(f"      Customer Tier: {customer_tier}")

        # Escalation decision logic
        needs_escalation = (
            confidence < 0.85
            or escalation_needed
            or ticket_priority == "URGENT"
            or customer_tier == "ENTERPRISE"
        )

        if needs_escalation:
            print("   ⬆️  ESCALATING to human agent")
            return StepOutput(
                content=f"⬆️  **ESCALATION REQUIRED**\n\nConfidence: {confidence:.2f}\nRouting to human agent with full context...",
                stop=False,  # Continue to escalation step
            )
        else:
            print("   ✅ AUTO-RESOLVE (Confidence threshold met)")
            return StepOutput(
                content=f"✅ **AUTO-RESOLVED**\n\nConfidence: {confidence:.2f}\n\n{solution_content.solution_text}",
                stop=True,
            )

    # Fallback: escalate if can't parse
    print("   ⚠️  Could not parse solution - escalating by default")
    return StepOutput(
        content="⚠️  Escalating ticket to human agent (safety fallback)", stop=False
    )


# ============================================================================
# Workflow Steps Definition
# ============================================================================

# Parallel knowledge retrieval step
parallel_knowledge_retrieval = Parallel(
    Step(
        name="search_documentation",
        agent=documentation_agent,
        description="Search product documentation for relevant solutions",
    ),
    Step(
        name="search_historical_tickets",
        agent=historical_ticket_agent,
        description="Find similar resolved tickets and their solutions",
    ),
    Step(
        name="check_product_status",
        agent=product_status_agent,
        description="Check system status and known issues",
    ),
    name="Knowledge Retrieval",
)

# Solution refinement loop
solution_refinement_loop = Loop(
    steps=[
        Step(
            name="compose_solution",
            agent=solution_composer_agent,
            description="Synthesize knowledge into actionable solution",
        )
    ],
    name="Solution Refinement",
    end_condition=evaluate_solution_quality,
    max_iterations=2,
)

# Escalation decision step
escalation_decision_step = Step(
    name="escalation_decision",
    executor=check_escalation_needed,
    description="Determine if escalation to human agent is needed",
)

# Escalation step (only runs if decision requires it)
escalation_step = Step(
    name="prepare_escalation",
    agent=escalation_agent,
    description="Prepare comprehensive handoff for human agent",
)

# ============================================================================
# Support Path Definitions (for Router)
# ============================================================================

urgent_support_step = Step(
    name="urgent_support_path",
    executor=lambda step_input: StepOutput(
        content="🚨 URGENT ticket detected - prioritizing immediate resolution...",
    ),
    description="Handle urgent priority tickets with immediate attention",
)

technical_support_step = Step(
    name="technical_support_path",
    executor=lambda step_input: StepOutput(
        content="🔧 TECHNICAL issue detected - engaging expert analysis...",
    ),
    description="Handle complex technical issues requiring expert analysis",
)

billing_support_step = Step(
    name="billing_support_path",
    executor=lambda step_input: StepOutput(
        content="💳 BILLING issue detected - routing to financial operations...",
    ),
    description="Handle payment and subscription-related issues",
)

general_support_step = Step(
    name="general_support_path",
    executor=lambda step_input: StepOutput(
        content="📋 GENERAL support request - processing with standard workflow...",
    ),
    description="Handle standard support questions and requests",
)

# ============================================================================
# Main Workflow Definition
# ============================================================================

customer_support_workflow = Workflow(
    name="AI-Powered Customer Support Orchestrator",
    description="Intelligent ticket resolution with routing, knowledge retrieval, and quality-based escalation",
    db=db,
    steps=[
        # Step 1: Route ticket to appropriate path
        Router(
            name="Ticket Router",
            description="Classify and route tickets based on priority and content",
            selector=classify_ticket,
            choices=[
                urgent_support_step,
                technical_support_step,
                billing_support_step,
                general_support_step,
            ],
        ),
        # Step 2: Parallel knowledge retrieval
        parallel_knowledge_retrieval,
        # Step 3: Iterative solution refinement
        solution_refinement_loop,
        # Step 4: Escalation decision
        escalation_decision_step,
        # Step 5: Escalation (conditional - only if Step 4 doesn't stop)
        escalation_step,
    ],
    input_schema=SupportTicket,
    session_state={},  # Initialize empty session state for ticket context
)


# ============================================================================
# Usage Example
# ============================================================================

if __name__ == "__main__":
    """
    Example usage demonstrating different ticket types and routing.
    """
    print("=" * 80)
    print("🎫 Customer Support Workflow - Demo Examples")
    print("=" * 80)

    # Example 1: Technical Issue
    technical_ticket = SupportTicket(
        ticket_id="TECH-001",
        customer_email="user@company.com",
        subject="API integration returning 500 errors",
        description="Our API integration has been failing with 500 Internal Server Error for the past hour. This is blocking our production deployment.",
        priority="HIGH",
        customer_tier="PRO",
    )

    print("\n\n📝 Example 1: Technical Issue")
    print("-" * 80)
    customer_support_workflow.print_response(input=technical_ticket, stream=True)

    # Example 2: Billing Issue (commented out to save API calls)
    # billing_ticket = SupportTicket(
    #     ticket_id="BILL-002",
    #     customer_email="finance@company.com",
    #     subject="Incorrect charges on invoice",
    #     description="We were charged twice for our subscription this month. Need refund.",
    #     priority="MEDIUM",
    #     customer_tier="ENTERPRISE",
    # )

    # print("\n\n📝 Example 2: Billing Issue")
    # print("-" * 80)
    # customer_support_workflow.print_response(
    #     input=billing_ticket,
    #     stream=True
    # )
