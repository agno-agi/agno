"""
Example: Background Output Evaluation with Agent-as-Judge

This example demonstrates how to use a validator agent to evaluate the main agent's
output as a background task. Unlike blocking validation, background evaluation:
- Does NOT block the response to the user
- Logs evaluation results for monitoring and analytics
- Can trigger alerts or store metrics without affecting latency

Use cases:
- Quality monitoring in production
- A/B testing response quality
- Compliance auditing
- Building evaluation datasets
"""

import asyncio
from datetime import datetime

from agno.agent import Agent
from agno.db.sqlite import AsyncSqliteDb
from agno.hooks.decorator import hook
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.run.agent import RunOutput
from pydantic import BaseModel


class EvaluationResult(BaseModel):
    """Structured output for the evaluator agent."""

    is_helpful: bool
    is_accurate: bool
    is_well_structured: bool
    quality_score: float  # 0.0 - 1.0
    strengths: list[str]
    areas_for_improvement: list[str]
    summary: str


# Create the evaluator agent once (not in the hook for performance)
evaluator_agent = Agent(
    name="OutputEvaluator",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are an expert at evaluating AI assistant responses.",
        "Analyze responses for:",
        "1. HELPFULNESS: Does it address the user's question?",
        "2. ACCURACY: Is the information correct and reliable?",
        "3. STRUCTURE: Is it well-organized and easy to understand?",
        "",
        "Provide a quality_score from 0.0 to 1.0 where:",
        "- 0.0-0.3: Poor quality, major issues",
        "- 0.4-0.6: Acceptable, some improvements needed",
        "- 0.7-0.8: Good quality, minor issues",
        "- 0.9-1.0: Excellent quality",
        "",
        "Be fair and balanced in your evaluation.",
    ],
    output_schema=EvaluationResult,
)


@hook(run_in_background=True)
async def evaluate_output_quality(run_output: RunOutput, agent: Agent) -> None:
    """
    Background post-hook that evaluates the agent's response quality.

    This runs after the response is sent to the user, so it doesn't add latency.
    Results are logged for monitoring purposes.
    """
    # Skip if no content to evaluate
    if not run_output.content or len(str(run_output.content).strip()) < 10:
        print("[Evaluator] Skipping evaluation - response too short")
        return

    print(f"[Evaluator] Starting background evaluation for run: {run_output.run_id}")

    # Run the evaluation
    evaluation_prompt = f"""
    Evaluate this AI assistant response:

    User Query: {run_output.input_content if hasattr(run_output, "input_content") else "Unknown"}

    Assistant Response:
    {run_output.content}
    """

    result = await evaluator_agent.arun(input=evaluation_prompt)
    evaluation: EvaluationResult = result.content

    # Log the evaluation results
    timestamp = datetime.now().isoformat()
    print("\n" + "=" * 60)
    print(f"[Evaluator] Evaluation Complete - {timestamp}")
    print("=" * 60)
    print(f"Run ID: {run_output.run_id}")
    print(f"Agent: {agent.name}")
    print(f"\nQuality Score: {evaluation.quality_score:.2f}/1.00")
    print(f"Helpful: {evaluation.is_helpful}")
    print(f"Accurate: {evaluation.is_accurate}")
    print(f"Well-Structured: {evaluation.is_well_structured}")

    if evaluation.strengths:
        print("\nStrengths:")
        for strength in evaluation.strengths:
            print(f"  - {strength}")

    if evaluation.areas_for_improvement:
        print("\nAreas for Improvement:")
        for area in evaluation.areas_for_improvement:
            print(f"  - {area}")

    print(f"\nSummary: {evaluation.summary}")
    print("=" * 60 + "\n")

    # In production, you could:
    # - Store in database for analytics
    # - Send alerts if quality_score < threshold
    # - Log to observability platform
    # - Build evaluation datasets


@hook(run_in_background=True)
async def check_response_safety(run_output: RunOutput, agent: Agent) -> None:
    """
    Background post-hook that checks response safety.

    Runs concurrently with other background hooks.
    """
    print(f"[Safety Check] Analyzing response safety for run: {run_output.run_id}")

    # Simulate safety check processing
    await asyncio.sleep(1)

    content = str(run_output.content).lower()

    # Simple safety checks (in production, use a more sophisticated approach)
    safety_flags = []
    if any(word in content for word in ["password", "credential", "secret"]):
        safety_flags.append("Contains potentially sensitive terms")

    if len(safety_flags) > 0:
        print(f"[Safety Check] Flags found: {safety_flags}")
    else:
        print("[Safety Check] No safety concerns detected")


# Setup database for agent storage
db = AsyncSqliteDb(db_file="tmp/evaluation.db")

# Create the main agent with background evaluation hooks
main_agent = Agent(
    id="support-agent",
    name="CustomerSupportAgent",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=[
        "You are a helpful customer support agent.",
        "Provide clear, accurate, and friendly responses.",
        "If you don't know something, say so honestly.",
    ],
    db=db,
    post_hooks=[
        evaluate_output_quality,  # Runs in background
        check_response_safety,  # Runs in background
    ],
    markdown=True,
)

# Create AgentOS
agent_os = AgentOS(agents=[main_agent])
app = agent_os.get_app()


# Flow:
# 1. User sends request to /agents/support-agent/runs
# 2. Agent processes and generates response
# 3. Response is sent to user immediately
# 4. Background hooks run concurrently:
#    - evaluate_output_quality: Evaluator agent scores the response
#    - check_response_safety: Safety checks run in parallel
# 5. Evaluation results are logged for monitoring

# Example requests:
# curl -X POST http://localhost:7777/agents/support-agent/runs \
#   -F "message=How do I reset my password?" -F "stream=false"
#
# curl -X POST http://localhost:7777/agents/support-agent/runs \
#   -F "message=Explain the difference between HTTP and HTTPS" -F "stream=false"

if __name__ == "__main__":
    agent_os.serve(app="background_output_evaluation:app", port=7777, reload=True)
