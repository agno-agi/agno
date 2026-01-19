from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.workflow import Step, Workflow
from agno.workflow.types import StepInput, StepOutput

# Create agents
security_scanner = Agent(
    name="Security Scanner",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a security scanner. Analyze the provided code or system for security vulnerabilities.",
        "Return 'SECURE' if no critical vulnerabilities found.",
        "Return 'VULNERABLE' if critical security issues are detected.",
        "Explain your findings briefly.",
    ],
)

code_deployer = Agent(
    name="Code Deployer",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Deploy the security-approved code to production environment.",
)

monitoring_agent = Agent(
    name="Monitoring Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions="Set up monitoring and alerts for the deployed application.",
)


def security_gate(step_input: StepInput) -> StepOutput:
    """
    Security gate that stops deployment if vulnerabilities found
    """
    security_result = step_input.previous_step_content or ""
    print(f"🔍 Security scan result: {security_result}")

    if "VULNERABLE" in security_result.upper():
        return StepOutput(
            content="🚨 SECURITY ALERT: Critical vulnerabilities detected. Deployment blocked for security reasons.",
            stop=True,  # Stop the entire workflow to prevent insecure deployment
        )
    else:
        return StepOutput(
            content="✅ Security check passed. Proceeding with deployment...",
            stop=False,
        )


# Create deployment workflow with security gate
workflow = Workflow(
    name="Secure Deployment Pipeline",
    description="Deploy code only if security checks pass",
    steps=[
        Step(name="Security Scan", agent=security_scanner),
        Step(name="Security Gate", executor=security_gate),  # May stop here
        Step(name="Deploy Code", agent=code_deployer),  # Only if secure
        Step(name="Setup Monitoring", agent=monitoring_agent),  # Only if deployed
    ],
)

if __name__ == "__main__":
    print("\n=== Testing VULNERABLE code deployment ===")
    workflow.print_response(input="Scan this code: exec(input('Enter command: '))")

    print("=== Testing SECURE code deployment ===")
    workflow.print_response(input="Scan this code: def hello(): return 'Hello World'")
