"""
Example demonstrating how to use pre_hook and post_hook with Agno Teams.

This example shows how to:
1. Pre-hook: Comprehensive input transformation using an AI agent
2. Transform input to be more relevant to the team's collective purpose
3. Leverage team context for better input preparation
"""

from typing import Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.team import TeamRunInput
from agno.session.team import TeamSession
from agno.team import Team
from agno.utils.log import log_debug


def transform_team_input(
    run_input: TeamRunInput,
    team: Team,
    session: TeamSession,
    user_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
) -> None:
    """
    Pre-hook: Rewrite the input to be more relevant to the team's collective purpose.

    This hook analyzes the team's member capabilities and transforms the input
    to leverage the team's collective expertise more effectively.
    """
    log_debug(
        f"Transforming team input: {run_input.input_content} for user {user_id} and session {session.session_id}"
    )

    # Get team member information for context
    team_capabilities = []
    for member in team.members:
        if hasattr(member, "description") and member.description:
            team_capabilities.append(f"- {member.name}: {member.description}")
        else:
            team_capabilities.append(f"- {member.name}")

    team_context = f"Team '{team.name}' with members:\n" + "\n".join(team_capabilities)

    # Input transformation agent
    transformer_agent = Agent(
        name="Team Input Transformer",
        model=OpenAIChat(id="gpt-5-mini"),
        instructions=[
            "You are a team input transformation specialist.",
            "Rewrite user requests to maximize the collective capabilities of the team.",
            "Consider how different team members can contribute to addressing the request.",
            "Break down complex requests into components that different specialists can handle.",
            "Keep the input comprehensive but well-structured for team collaboration.",
            "Maintain the original intent while optimizing for team-based execution.",
            "Don't put any additional text at the beginning or end of the request. Don't add **Revised User Request** etc."
            "Address your output to the target team (as if the user made the request to the team). End the request with `Please give me advice based on this request.`",
        ],
        debug_mode=debug_mode,
    )

    transformation_result = transformer_agent.run(
        input=f"""
        Team Context: {team_context}
        
        Original User Request: '{run_input.input_content}'
        
        Transform this request to be more effective for this team to work on collaboratively.
        Consider each member's expertise and how they can best contribute.
        """
    )

    # Overwrite the input with the transformed input
    run_input.input_content = transformation_result.content
    log_debug(f"Transformed team input: {run_input.input_content}")


# Create a multi-disciplinary consulting team with input transformation
research_agent = Agent(
    name="Research Analyst",
    model=OpenAIChat(id="gpt-5-mini"),
    role="Expert in market research, data analysis, and competitive intelligence",
)

strategy_agent = Agent(
    name="Strategy Consultant",
    model=OpenAIChat(id="gpt-5-mini"),
    role="Specialist in business strategy, planning, and decision frameworks",
)

financial_agent = Agent(
    name="Financial Advisor",
    model=OpenAIChat(id="gpt-5-mini"),
    role="Expert in financial planning, investment analysis, and risk assessment",
)

consulting_team = Team(
    name="Business Consulting Team",
    model=OpenAIChat(id="gpt-5-mini"),
    members=[research_agent, strategy_agent, financial_agent],
    pre_hooks=[transform_team_input],
    instructions=[
        "Work collaboratively to provide comprehensive business insights.",
        "Coordinate your expertise to deliver actionable business advice.",
        "Give the user advice based on their request.",
    ],
    debug_mode=True,
)

consulting_team.print_response(
    input="I want to start a food truck business in downtown Austin. Help me understand if this is viable.",
    session_id="test_session",
    user_id="test_user",
    stream=True,
)
