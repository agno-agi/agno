"""
Condition With Else
===================

Demonstrates `Condition(..., else_steps=[...])` for routing between technical and general support branches.
"""

import asyncio

from agno.agent.agent import Agent
from agno.workflow.condition import Condition
from agno.workflow.step import Step
from agno.workflow.types import StepInput
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
diagnostic_agent = Agent(
    name="Diagnostic Agent",
    instructions=(
        "You are a diagnostic specialist. Analyze the technical issue described "
        "by the customer and list the most likely root causes. Be concise."
    ),
)

engineering_agent = Agent(
    name="Engineering Agent",
    instructions=(
        "You are a senior engineer. Given the diagnostic analysis, provide "
        "step-by-step troubleshooting instructions the customer can follow."
    ),
)

general_support_agent = Agent(
    name="General Support Agent",
    instructions=(
        "You are a friendly customer support agent. Help the customer with "
        "their non-technical question — billing, account, shipping, returns, etc."
    ),
)

followup_agent = Agent(
    name="Follow-Up Agent",
    instructions=(
        "You are a follow-up specialist. Summarize what was resolved so far "
        "and ask the customer if they need anything else."
    ),
)


# ---------------------------------------------------------------------------
# Define Condition Evaluator
# ---------------------------------------------------------------------------
def is_technical_issue(step_input: StepInput) -> bool:
    text = (step_input.input or "").lower()
    tech_keywords = [
        "error",
        "bug",
        "crash",
        "not working",
        "broken",
        "install",
        "update",
        "password reset",
        "api",
        "timeout",
        "exception",
        "failed",
        "logs",
        "debug",
    ]
    return any(kw in text for kw in tech_keywords)


# ---------------------------------------------------------------------------
# Define Steps
# ---------------------------------------------------------------------------
diagnose_step = Step(
    name="Diagnose",
    description="Run diagnostics on the technical issue",
    agent=diagnostic_agent,
)

engineer_step = Step(
    name="Engineer",
    description="Provide engineering-level troubleshooting",
    agent=engineering_agent,
)

general_step = Step(
    name="GeneralSupport",
    description="Handle non-technical customer queries",
    agent=general_support_agent,
)

followup_step = Step(
    name="FollowUp",
    description="Wrap up with a follow-up message",
    agent=followup_agent,
)

# ---------------------------------------------------------------------------
# Create Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Customer Support Router",
    description="Routes customer queries through technical or general support pipelines",
    steps=[
        Condition(
            name="TechnicalTriage",
            description="Route to technical or general support based on query content",
            evaluator=is_technical_issue,
            steps=[diagnose_step, engineer_step],
            else_steps=[general_step],
        ),
        followup_step,
    ],
)

workflow_2 = Workflow(
    name="Customer Support Router",
    steps=[
        Condition(
            name="TechnicalTriage",
            evaluator=is_technical_issue,
            steps=[diagnose_step, engineer_step],
            else_steps=[general_step],
        ),
        followup_step,
    ],
)

# ---------------------------------------------------------------------------
# Run Workflow
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("Test 1: Technical query (expects if-branch)")
    print("=" * 60)
    workflow.print_response(
        "My app keeps crashing with a timeout error after the latest update"
    )

    print()
    print("=" * 60)
    print("Test 2: General query (expects else-branch)")
    print("=" * 60)
    workflow_2.print_response("How do I change my shipping address for order #12345?")

    print()
    print("=" * 60)
    print("Async Technical Query")
    print("=" * 60)
    asyncio.run(
        workflow.aprint_response(
            "My app keeps crashing with a timeout error after the latest update"
        )
    )

    print()
    print("=" * 60)
    print("Async General Query")
    print("=" * 60)
    asyncio.run(
        workflow_2.aprint_response(
            "How do I change my shipping address for order #12345?"
        )
    )
