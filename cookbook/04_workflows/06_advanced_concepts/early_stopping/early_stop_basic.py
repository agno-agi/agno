"""
Early Stop Basic
================

Demonstrates early termination with `StepOutput(stop=True)` across direct steps, `Steps` containers, and agent/function workflows.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.websearch import WebSearchTools
from agno.workflow import Step, Workflow
from agno.workflow.steps import Steps
from agno.workflow.types import StepInput, StepOutput

# ---------------------------------------------------------------------------
# Create Agents (Security Deployment)
# ---------------------------------------------------------------------------
security_scanner = Agent(
    name="Security Scanner",
    model=OpenAIChat(id="gpt-5.2"),
    instructions=[
        "You are a security scanner. Analyze the provided code or system for security vulnerabilities.",
        "Return 'SECURE' if no critical vulnerabilities found.",
        "Return 'VULNERABLE' if critical security issues are detected.",
        "Explain your findings briefly.",
    ],
)

code_deployer = Agent(
    name="Code Deployer",
    model=OpenAIChat(id="gpt-5.2"),
    instructions="Deploy the security-approved code to production environment.",
)

monitoring_agent = Agent(
    name="Monitoring Agent",
    model=OpenAIChat(id="gpt-5.2"),
    instructions="Set up monitoring and alerts for the deployed application.",
)


# ---------------------------------------------------------------------------
# Define Security Gate
# ---------------------------------------------------------------------------
def security_gate(step_input: StepInput) -> StepOutput:
    security_result = step_input.previous_step_content or ""
    print(f"Security scan result: {security_result}")

    if "VULNERABLE" in security_result.upper():
        return StepOutput(
            content="[ALERT] SECURITY ALERT: Critical vulnerabilities detected. Deployment blocked for security reasons.",
            stop=True,
        )
    return StepOutput(
        content="[OK] Security check passed. Proceeding with deployment...",
        stop=False,
    )


# ---------------------------------------------------------------------------
# Create Security Workflow
# ---------------------------------------------------------------------------
security_workflow = Workflow(
    name="Secure Deployment Pipeline",
    description="Deploy code only if security checks pass",
    steps=[
        Step(name="Security Scan", agent=security_scanner),
        Step(name="Security Gate", executor=security_gate),
        Step(name="Deploy Code", agent=code_deployer),
        Step(name="Setup Monitoring", agent=monitoring_agent),
    ],
)

# ---------------------------------------------------------------------------
# Create Agents (Content Quality Pipeline)
# ---------------------------------------------------------------------------
content_creator = Agent(
    name="Content Creator",
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[WebSearchTools()],
    instructions="Create engaging content on the given topic. Research and write comprehensive articles.",
)

fact_checker = Agent(
    name="Fact Checker",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Verify facts and check accuracy of content. Flag any misinformation.",
)

editor = Agent(
    name="Editor",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Edit and polish content for publication. Ensure clarity and flow.",
)

publisher = Agent(
    name="Publisher",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Prepare content for publication and handle final formatting.",
)


# ---------------------------------------------------------------------------
# Define Quality Gate
# ---------------------------------------------------------------------------
def content_quality_gate(step_input: StepInput) -> StepOutput:
    content = step_input.previous_step_content or ""

    if len(content) < 100:
        return StepOutput(
            step_name="content_quality_gate",
            content="[FAIL] QUALITY CHECK FAILED: Content too short. Stopping workflow.",
            stop=True,
        )

    problematic_keywords = ["fake", "misinformation", "unverified", "conspiracy"]
    if any(keyword in content.lower() for keyword in problematic_keywords):
        return StepOutput(
            step_name="content_quality_gate",
            content="[FAIL] QUALITY CHECK FAILED: Problematic content detected. Stopping workflow.",
            stop=True,
        )

    return StepOutput(
        step_name="content_quality_gate",
        content="[PASS] QUALITY CHECK PASSED: Content meets quality standards.",
        stop=False,
    )


# ---------------------------------------------------------------------------
# Create Content Workflow
# ---------------------------------------------------------------------------
content_pipeline = Steps(
    name="content_pipeline",
    description="Content creation pipeline with quality gates",
    steps=[
        Step(name="create_content", agent=content_creator),
        Step(name="quality_gate", executor=content_quality_gate),
        Step(name="fact_check", agent=fact_checker),
        Step(name="edit_content", agent=editor),
        Step(name="publish", agent=publisher),
    ],
)

content_workflow = Workflow(
    name="Content Creation with Quality Gate",
    description="Content creation workflow with early termination on quality issues",
    steps=[
        content_pipeline,
        Step(name="final_review", agent=editor),
    ],
)

# ---------------------------------------------------------------------------
# Create Agents (Data Validation Workflow)
# ---------------------------------------------------------------------------
data_validator = Agent(
    name="Data Validator",
    model=OpenAIChat(id="gpt-5.2"),
    instructions=[
        "You are a data validator. Analyze the provided data and determine if it's valid.",
        "For data to be VALID, it must meet these criteria:",
        "- user_count: Must be a positive number (> 0)",
        "- revenue: Must be a positive number (> 0)",
        "- date: Must be in a reasonable date format (YYYY-MM-DD)",
        "Return exactly 'VALID' if all criteria are met.",
        "Return exactly 'INVALID' if any criteria fail.",
        "Also briefly explain your reasoning.",
    ],
)

data_processor = Agent(
    name="Data Processor",
    model=OpenAIChat(id="gpt-5.2"),
    instructions="Process and transform the validated data.",
)

report_generator = Agent(
    name="Report Generator",
    model=OpenAIChat(id="gpt-5.2"),
    instructions="Generate a final report from processed data.",
)


# ---------------------------------------------------------------------------
# Define Validation Gate
# ---------------------------------------------------------------------------
def early_exit_validator(step_input: StepInput) -> StepOutput:
    validation_result = step_input.previous_step_content or ""

    if "INVALID" in validation_result.upper():
        return StepOutput(
            content="[FAIL] Data validation failed. Workflow stopped early to prevent processing invalid data.",
            stop=True,
        )
    return StepOutput(
        content="[PASS] Data validation passed. Continuing with processing...",
        stop=False,
    )


# ---------------------------------------------------------------------------
# Create Data Workflow
# ---------------------------------------------------------------------------
data_workflow = Workflow(
    name="Data Processing with Early Exit",
    description="Process data but stop early if validation fails",
    steps=[
        data_validator,
        early_exit_validator,
        data_processor,
        report_generator,
    ],
)

# ---------------------------------------------------------------------------
# Run Workflows
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("\n=== Testing VULNERABLE code deployment ===")
    security_workflow.print_response(
        input="Scan this code: exec(input('Enter command: '))"
    )

    print("=== Testing SECURE code deployment ===")
    security_workflow.print_response(
        input="Scan this code: def hello(): return 'Hello World'"
    )

    print("\n=== Test: Short content (should stop early) ===")
    content_workflow.print_response(
        input="Write a short note about conspiracy theories",
        markdown=True,
        stream=True,
    )

    print("\n=== Testing with INVALID data ===")
    data_workflow.print_response(
        input="Process this data: {'user_count': -50, 'revenue': 'invalid_amount', 'date': 'bad_date'}"
    )

    print("=== Testing with VALID data ===")
    data_workflow.print_response(
        input="Process this data: {'user_count': 1000, 'revenue': 50000, 'date': '2024-01-15'}"
    )
