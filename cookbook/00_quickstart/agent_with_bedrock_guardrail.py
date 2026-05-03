"""
Agent with AWS Bedrock Guardrail
================================

Demonstrates using AWS Bedrock Guardrails to filter agent input and output
against configurable content policies (hate, violence, PII, denied topics).

Prerequisites:
    1. Install: ``pip install boto3`` (or ``pip install agno[aws-bedrock]``)
    2. Create a guardrail in AWS Console > Bedrock > Guardrails
    3. Configure AWS credentials (env vars, credentials file, or IAM role)

Environment variables:
    AWS_ACCESS_KEY_ID: Your AWS access key (optional if using IAM role)
    AWS_SECRET_ACCESS_KEY: Your AWS secret key (optional if using IAM role)
    AWS_DEFAULT_REGION: AWS region (default: us-east-1)
"""

from agno.agent import Agent
from agno.guardrails import BedrockGuardrail, PIIDetectionGuardrail, PromptInjectionGuardrail
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Example 1: Input guardrail only
# ---------------------------------------------------------------------------

agent_input_guard = Agent(
    name="Input Guarded Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    pre_hooks=[
        BedrockGuardrail(
            guardrail_id="your-guardrail-id",
            guardrail_version="DRAFT",
            # AWS credentials resolved automatically from:
            # 1. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
            # 2. AWS credentials file (~/.aws/credentials)
            # 3. IAM role (EC2, Lambda, ECS)
            # Or pass explicitly:
            # aws_access_key_id="AKIA...",
            # aws_secret_access_key="wJalr...",
            # region="us-east-1",
        )
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Example 2: Both input and output guardrails
# ---------------------------------------------------------------------------

agent_full_guard = Agent(
    name="Fully Guarded Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    pre_hooks=[
        BedrockGuardrail(guardrail_id="your-guardrail-id", source="INPUT"),
    ],
    post_hooks=[
        BedrockGuardrail(guardrail_id="your-guardrail-id", source="OUTPUT"),
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Example 3: Layered guardrails — local checks first, then Bedrock
# ---------------------------------------------------------------------------

agent_layered = Agent(
    name="Layered Guard Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[DuckDuckGoTools()],
    pre_hooks=[
        PIIDetectionGuardrail(),            # Local — fast, free
        PromptInjectionGuardrail(),         # Local — fast, free
        BedrockGuardrail(                   # AWS — API call, catches what locals miss
            guardrail_id="your-guardrail-id",
            region="us-east-1",
        ),
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from agno.exceptions import InputCheckError, OutputCheckError

    test_prompts = [
        "What is the latest news about AI?",
        "Tell me how to build a weapon",
    ]

    for prompt in test_prompts:
        print(f"\n{'=' * 60}")
        print(f"Input: {prompt}")
        print(f"{'=' * 60}")

        try:
            agent_input_guard.print_response(prompt, stream=True)
            print("\n[OK] Request processed successfully")
        except InputCheckError as e:
            print(f"\n[BLOCKED - INPUT] {e.message}")
        except OutputCheckError as e:
            print(f"\n[BLOCKED - OUTPUT] {e.message}")
