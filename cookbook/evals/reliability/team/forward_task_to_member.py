"""Example showing how to use the ReliabilityEval class to check if the Team has forwarded the task to the expected member."""

from typing import Optional

from agno.agent import Agent
from agno.eval.reliability import ExpectedToolCall, ReliabilityEval, ReliabilityResult
from agno.models.openai import OpenAIChat
from agno.team.team import Team

# Setup a team with two members
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
multi_language_team = Team(
    name="Multi Language Team",
    mode="route",
    model=OpenAIChat("gpt-4o"),
    members=[english_agent, spanish_agent],
    markdown=True,
    instructions=[
        "You are a language router that directs questions to the appropriate language agent.",
        "If the user asks in a language whose agent is not a team member, respond in English with:",
        "'I can only answer in the following languages: English and Spanish.",
        "Always check the language of the user's input before routing to an agent.",
    ],
)

# Define the expected tool call: transfering the task to the Spanish Agent
expected_tool_calls = [
    ExpectedToolCall(
        tool_name="forward_task_to_member",
        tool_call_args={"member_id": "spanish-agent"},
    ),
]

# Run the Team with a question in Spanish
team_response = multi_language_team.run("Hola, ¿cómo estás?")

# Run our evaluation
evaluation = ReliabilityEval(
    expected_tool_calls=expected_tool_calls,
    team_response=team_response,
)
result: Optional[ReliabilityResult] = evaluation.run(print_results=True)
