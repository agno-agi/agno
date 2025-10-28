"""
This example demonstrates how agents automatically inherit the model from their Team when not explicitly set.

This is particularly useful when:
- Using non-OpenAI models (Claude, Ollama, VLLM, etc.) to avoid manual model configuration on every agent
- Preventing API key errors when team uses a different provider than the default OpenAI
- Simplifying code by setting the model once on the team instead of on each agent

Key behaviors:
1. Agents without explicit models inherit from their team
2. Agents with explicit models keep their own configuration
3. Nested teams and their members inherit from their immediate parent team
4. All model types are inherited: model, reasoning_model, parser_model, output_model
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.team.team import Team

# These agents don't have models set
researcher = Agent(
    name="Researcher",
    role="Research and gather information",
    instructions=["Be thorough and detailed"],
)

writer = Agent(
    name="Writer",
    role="Write content based on research",
    instructions=["Write clearly and concisely"],
)

# This agent has a model set
editor = Agent(
    name="Editor",
    role="Edit and refine content",
    model=OpenAIChat(id="gpt-4o-mini"),
    instructions=["Ensure clarity and correctness"],
)

# Nested team setup
analyst = Agent(
    name="Analyst",
    role="Analyze data and provide insights",
)

sub_team = Team(
    name="Analysis Team",
    model=Claude(id="claude-3-5-haiku-20241022"),
    members=[analyst],
)


# Main team with all members
team = Team(
    name="Content Production Team",
    model=Claude(id="claude-3-5-sonnet-20241022"),
    members=[researcher, writer, editor, sub_team],
    instructions=[
        "Research the topic thoroughly",
        "Write clear and engaging content",
        "Edit for quality and clarity",
        "Coordinate the entire process",
    ],
)

if __name__ == "__main__":
    team.initialize_team()

    # researcher and writer inherit Claude Sonnet from team
    print(f"Researcher: {researcher.model.id}")
    print(f"Writer: {writer.model.id}")

    # editor keeps its explicit model
    print(f"Editor: {editor.model.id}")

    # analyst inherits Claude Haiku from its sub-team
    print(f"Analyst: {analyst.model.id}")

    team.print_response(
        "Write a brief article about AI", stream=True
    )
