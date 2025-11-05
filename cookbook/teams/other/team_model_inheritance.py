"""
This example demonstrates how agents automatically inherit models from their Team.

This is particularly useful when:
- Using non-OpenAI models (Claude, Ollama, VLLM, etc.) to avoid manual model configuration on every agent
- Preventing API key errors when team uses a different provider than the default OpenAI
- Simplifying code by setting the model once on the team instead of on each agent

Key behaviors:
1. Primary model is always inherited by agents without explicit models
2. Secondary models (output_model, parser_model, reasoning_model) are not inherited by default
3. Use inherit_secondary_models parameter to opt-in to secondary model inheritance
4. Agents with explicit models keep their own configuration
5. Nested teams and their members inherit from their immediate parent team
"""

from agno.agent import Agent
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
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[analyst],
)


# Main team with all members and secondary model inheritance
team = Team(
    name="Content Production Team",
    model=OpenAIChat(id="gpt-4o"),
    output_model=OpenAIChat(id="gpt-4o-mini"),  # For structured output from team
    parser_model=OpenAIChat(id="gpt-4o-mini"),  # For parsing responses
    # Only inherit output_model to members, not parser_model
    inherit_secondary_models=["output_model"],
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
    print(f"Researcher model: {researcher.model.id}")
    print(f"Writer model: {writer.model.id}")
    # editor keeps its explicit model
    print(f"Editor model: {editor.model.id}")
    # analyst inherits Claude Haiku from its sub-team
    print(f"Analyst model: {analyst.model.id}")

    # output_model is inherited because it's in inherit_secondary_models list
    print(
        f"Researcher output_model: {researcher.output_model.id if researcher.output_model else 'None'}"
    )
    print(
        f"Writer output_model: {writer.output_model.id if writer.output_model else 'None'}"
    )
    # parser_model is NOT inherited because it's not in inherit_secondary_models list
    print(
        f"Researcher parser_model: {researcher.parser_model.id if researcher.parser_model else 'None (not inherited)'}"
    )
    print(
        f"Writer parser_model: {writer.parser_model.id if writer.parser_model else 'None (not inherited)'}"
    )

    team.print_response("Write a brief article about AI", stream=True)
