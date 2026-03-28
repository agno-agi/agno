"""
Multi-Model Parallel Feedback
==============================
Query multiple feedback models at the same time. When you pass `models=[...]`,
ModelFeedbackTools sends the conversation to all models in parallel and returns
combined feedback.

This is useful when you want diverse perspectives:
- Different models have different strengths and biases
- Consensus across models increases confidence
- Disagreements highlight areas that need attention

Parallel execution:
- Sync: Uses ThreadPoolExecutor for concurrent API calls
- Async: Uses asyncio.gather for true parallel execution
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.openai import OpenAIChat
from agno.tools.model_feedback import ModelFeedbackTools

# ---------------------------------------------------------------------------
# Create Agent with multiple feedback models
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        ModelFeedbackTools(
            models=[
                Gemini(id="gemini-2.0-flash"),
                Claude(id="claude-sonnet-4-5-20250514"),
            ],
            aspects=["accuracy", "completeness", "tone"],
        )
    ],
    instructions=[
        "After drafting a response, use get_feedback to get opinions from multiple models.",
        "Compare the feedback from each model.",
        "Where they agree, the feedback is likely valid.",
        "Where they disagree, use your best judgment.",
        "Provide your final answer incorporating the strongest suggestions.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "What are the pros and cons of microservices vs monolithic architecture?",
        stream=True,
    )
