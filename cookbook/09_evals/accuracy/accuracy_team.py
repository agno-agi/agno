"""
Team Accuracy Evaluation
========================

Demonstrates evaluating language routing accuracy for a team.
"""

from typing import Optional

from agno.agent import Agent
from agno.eval.accuracy import AccuracyEval, AccuracyResult
from agno.models.openai import OpenAIChat
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Create Team Members
# ---------------------------------------------------------------------------
english_agent = Agent(
    name="English Agent",
    role="You only answer in English",
    model=OpenAIChat(id="gpt-4o"),
)
spanish_agent = Agent(
    name="Spanish Agent",
    role="You can only answer in Spanish",
    model=OpenAIChat(id="gpt-4o"),
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
multi_language_team = Team(
    name="Multi Language Team",
    model=OpenAIChat("gpt-4o"),
    members=[english_agent, spanish_agent],
    respond_directly=True,
    markdown=True,
    instructions=[
        "You are a language router that directs questions to the appropriate language agent.",
        "If the user asks in a language whose agent is not a team member, respond in English with:",
        "'I can only answer in the following languages: English and Spanish.",
        "Always check the language of the user's input before routing to an agent.",
    ],
)

# ---------------------------------------------------------------------------
# Create Evaluation
# ---------------------------------------------------------------------------
evaluation = AccuracyEval(
    name="Multi Language Team",
    model=OpenAIChat(id="o4-mini"),
    team=multi_language_team,
    input="Comment allez-vous?",
    expected_output="I can only answer in the following languages: English and Spanish.",
    num_iterations=1,
)

# ---------------------------------------------------------------------------
# Run Evaluation
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    result: Optional[AccuracyResult] = evaluation.run(print_results=True)
    assert result is not None and result.avg_score >= 8
