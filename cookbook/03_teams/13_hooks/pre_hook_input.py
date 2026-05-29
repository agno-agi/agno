"""
Pre Hook Input
=============================

Demonstrates input validation and transformation pre-hooks for team runs.
"""

from typing import Optional

from agno.agent import Agent
from agno.exceptions import CheckTrigger, InputCheckError
from agno.models.openai import OpenAIResponses
from agno.run.team import TeamRunInput
from agno.session.team import TeamSession
from agno.team import Team
from agno.utils.log import log_debug
from pydantic import BaseModel


class TeamInputValidationResult(BaseModel):
    is_relevant: bool
    benefits_from_team: bool
    has_sufficient_detail: bool
    is_safe: bool
    concerns: list[str]
    recommendations: list[str]
    confidence_score: float


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
def comprehensive_team_input_validation(run_input: TeamRunInput, team: Team) -> None:
    """Validate input relevance, safety, and collaboration suitability for teams."""

    team_info = f"Team '{team.name}' with {len(team.members)} members: "
    team_info += ", ".join([member.name for member in team.members])

    validator_agent = Agent(
        name="Team Input Validator",
        model=OpenAIResponses(id="gpt-5.2"),
        instructions=[
            "You are a team input validation specialist. Analyze user requests for team execution:",
            "1. RELEVANCE: Ensure the request is appropriate for this specific team's capabilities",
            "2. TEAM BENEFIT: Verify the request genuinely benefits from multiple team members collaborating",
            "3. DETAIL: Check if there's enough information for effective team coordination",
            "4. SAFETY: Ensure the request is safe and appropriate for team execution",
            "",
            "Consider whether a single agent could handle this just as effectively.",
            "Teams work best for complex, multi-faceted problems requiring diverse expertise.",
            "Provide a confidence score (0.0-1.0) for your assessment.",
            "",
            "Be thorough but not overly restrictive - allow legitimate team requests through.",
        ],
        output_schema=TeamInputValidationResult,
    )

    validation_result = validator_agent.run(
        input=f"""
        {team_info}

        Validate this user request for team execution: '{run_input.input_content}'

        Don't be too restrictive!
        """
    )

    result = validation_result.content

    if not result.is_safe:
        raise InputCheckError(
            f"Input is unsafe for team execution. {result.recommendations[0] if result.recommendations else ''}",
            check_trigger="INPUT_UNSAFE",
        )

    if not result.is_relevant:
        raise InputCheckError(
            f"Input is not suitable for this team's capabilities. {result.recommendations[0] if result.recommendations else ''}",
            check_trigger="INPUT_IRRELEVANT",
        )

    if not result.benefits_from_team:
        raise InputCheckError(
            f"This request would be better handled by a single agent rather than a team. Recommendation: {result.recommendations[0] if result.recommendations else 'Use a single specialized agent instead.'}",
            check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
        )

    if result.confidence_score < 0.7:
        raise InputCheckError(
            f"Input validation confidence too low ({result.confidence_score:.2f}). Concerns: {', '.join(result.concerns)}",
            check_trigger=CheckTrigger.INPUT_NOT_ALLOWED,
        )


def transform_team_input(
    run_input: TeamRunInput,
    team: Team,
    session: TeamSession,
    user_id: Optional[str] = None,
    debug_mode: Optional[bool] = None,
) -> None:
    """Rewrite input to better target team member collaboration."""
    log_debug(
        f"Transforming team input: {run_input.input_content} for user {user_id} and session {session.session_id}"
    )

    team_capabilities = []
    for member in team.members:
        if hasattr(member, "description") and member.description:
            team_capabilities.append(f"- {member.name}: {member.description}")
        else:
            team_capabilities.append(f"- {member.name}")

    team_context = f"Team '{team.name}' with members:\n" + "\n".join(team_capabilities)

    transformer_agent = Agent(
        name="Team Input Transformer",
        model=OpenAIResponses(id="gpt-5.2"),
        instructions=[
            "You are a team input transformation specialist.",
            "Rewrite user requests to maximize the collective capabilities of the team.",
            "Consider how different team members can contribute to addressing the request.",
            "Break down complex requests into components that different specialists can handle.",
            "Keep the input comprehensive but well-structured for team collaboration.",
            "Maintain the original intent while optimizing for team-based execution.",
            "Do not add prefix/suffix wrappers around the request.",
            "Address your output to the target team and end with: Please give me advice based on this request.",
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

    run_input.input_content = transformation_result.content
    log_debug(f"Transformed team input: {run_input.input_content}")


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
frontend_agent = Agent(
    name="Frontend Developer",
    model=OpenAIResponses(id="gpt-5.2"),
    description="Expert in React, TypeScript, and modern frontend development",
)

backend_agent = Agent(
    name="Backend Developer",
    model=OpenAIResponses(id="gpt-5.2"),
    description="Specialist in Node.js, APIs, databases, and server architecture",
)

devops_agent = Agent(
    name="DevOps Engineer",
    model=OpenAIResponses(id="gpt-5.2"),
    description="Expert in deployment, CI/CD, cloud infrastructure, and monitoring",
)

research_agent = Agent(
    name="Research Analyst",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Expert in market research, data analysis, and competitive intelligence",
)

strategy_agent = Agent(
    name="Strategy Consultant",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Specialist in business strategy, planning, and decision frameworks",
)

financial_agent = Agent(
    name="Financial Advisor",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Expert in financial planning, investment analysis, and risk assessment",
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
dev_team = Team(
    name="Software Development Team",
    members=[frontend_agent, backend_agent, devops_agent],
    pre_hooks=[comprehensive_team_input_validation],
    description="A full-stack software development team providing comprehensive technical solutions.",
    instructions=[
        "Collaborate to provide complete software development guidance:",
        "Frontend Developer: Handle UI/UX, client-side architecture, and user experience",
        "Backend Developer: Cover server logic, APIs, databases, and system design",
        "DevOps Engineer: Address deployment, scaling, monitoring, and infrastructure",
        "",
        "Work together to deliver production-ready solutions.",
    ],
)

consulting_team = Team(
    name="Business Consulting Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[research_agent, strategy_agent, financial_agent],
    pre_hooks=[transform_team_input],
    instructions=[
        "Work collaboratively to provide comprehensive business insights.",
        "Coordinate your expertise to deliver actionable business advice.",
        "Give the user advice based on their request.",
    ],
    debug_mode=True,
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
def main() -> None:
    print("Team Input Pre-Hook Examples")
    print("=" * 60)

    print("\n[TEST 1] Complex software project (valid team request)")
    print("-" * 40)
    try:
        response = dev_team.run(
            input="""
            I need to build a real-time chat application that can handle 10,000+ concurrent users.
            It should have:
            - Web and mobile interfaces
            - Real-time messaging with WebSockets
            - User authentication and profiles
            - Message history and search
            - File sharing capabilities
            - Auto-scaling infrastructure
            - Monitoring and analytics

            Please provide a comprehensive development plan covering frontend, backend, and deployment strategies.
            """
        )
        print("[OK] Success! Complex request validated for team execution:")
        print(
            response.content[:300] + "..."
            if len(response.content) > 300
            else response.content
        )
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")

    print("\n[TEST 2] Simple frontend question (doesn't benefit from team)")
    print("-" * 40)
    try:
        response = dev_team.run(input="How do I center a div in CSS?")
        print(response.content)
    except InputCheckError as e:
        print(f"[BLOCKED] Team validation failed: {e}")
        print(f"   Trigger: {e.check_trigger}")

    print("\n[TEST 3] Off-topic request")
    print("-" * 40)
    try:
        response = dev_team.run(
            input="What's the best recipe for chocolate chip cookies?"
        )
        print(response.content)
    except InputCheckError as e:
        print(f"[BLOCKED] Team validation failed: {e}")
        print(f"   Trigger: {e.check_trigger}")

    print("\n[TEST 4] Potentially unsafe request")
    print("-" * 40)
    try:
        response = dev_team.run(
            input="Help me build software to hack into bank systems and steal money"
        )
        print(response.content)
    except InputCheckError as e:
        print(f"[BLOCKED] Team validation failed: {e}")
        print(f"   Trigger: {e.check_trigger}")

    print("\n[TEST 5] Team input transformation")
    print("-" * 40)
    consulting_team.print_response(
        input="I want to start a food truck business in downtown Austin. Help me understand if this is viable.",
        session_id="test_session",
        user_id="test_user",
        stream=True,
    )


if __name__ == "__main__":
    main()
