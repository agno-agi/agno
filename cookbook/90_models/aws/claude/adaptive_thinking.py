"""
AWS Bedrock Claude Adaptive Thinking
====================================

Cookbook example demonstrating adaptive thinking with output_config on AWS Bedrock.

For Claude 4.6 Bedrock models, use adaptive thinking with the effort parameter
to control thinking depth. Valid effort values:
- "low": Most efficient, significant token savings
- "medium": Balanced approach with moderate savings
- "high": Default, high capability for complex reasoning
- "max": Absolute maximum capability (Opus 4.6 only)

Prerequisites:
- Set AWS credentials via environment variables or boto3 session
- Ensure you have access to Claude 4.6 models in your AWS region
"""

from agno.agent import Agent
from agno.models.aws import Claude

# ---------------------------------------------------------------------------
# Create Agent with Adaptive Thinking
# ---------------------------------------------------------------------------

agent = Agent(
    model=Claude(
        id="anthropic.claude-sonnet-4-6-20250514-v1:0",
        max_tokens=4096,
        thinking={"type": "adaptive"},
        output_config={"effort": "high"},
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Complex reasoning task that benefits from extended thinking
    agent.print_response(
        "Explain the key differences between recursion and iteration, "
        "and when you would choose one over the other in software development."
    )

    # With streaming
    agent.print_response(
        "What are the trade-offs between microservices and monolithic architectures?",
        stream=True,
    )
