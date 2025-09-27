"""
Example demonstrating how to use pre_hook for comprehensive input validation with Agno Teams.

This example shows how to validate inputs specifically for team-based scenarios:
1. Validate input is appropriate for team collaboration
2. Check if the request can benefit from multiple perspectives
3. Ensure sufficient detail for team coordination

Note: The "Message" panel will be updated with validation results after the pre-hook is executed.
"""

from agno.agent import Agent
from agno.exceptions import CheckTrigger, InputCheckError
from agno.models.openai import OpenAIChat
from agno.run.team import TeamRunInput
from agno.team import Team
from pydantic import BaseModel


class TeamInputValidationResult(BaseModel):
    is_relevant: bool
    benefits_from_team: bool
    has_sufficient_detail: bool
    is_safe: bool
    concerns: list[str]
    recommendations: list[str]
    confidence_score: float


def comprehensive_team_input_validation(run_input: TeamRunInput, team: Team) -> None:
    """
    Pre-hook: Comprehensive input validation specifically for team scenarios.

    This hook validates input for:
    - Relevance to the team's collective capabilities
    - Whether the request actually benefits from team collaboration
    - Sufficient detail for coordinated team response
    - Safety and appropriateness for team execution
    """

    # Build team context for validation
    team_info = f"Team '{team.name}' with {len(team.members)} members: "
    team_info += ", ".join([member.name for member in team.members])

    # Team-specific input validation agent
    validator_agent = Agent(
        name="Team Input Validator",
        model=OpenAIChat(id="gpt-5-mini"),
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

    # Check validation results
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


def main():
    # Create a software development team with comprehensive validation
    frontend_agent = Agent(
        name="Frontend Developer",
        model=OpenAIChat(id="gpt-5-mini"),
        description="Expert in React, TypeScript, and modern frontend development",
    )

    backend_agent = Agent(
        name="Backend Developer",
        model=OpenAIChat(id="gpt-5-mini"),
        description="Specialist in Node.js, APIs, databases, and server architecture",
    )

    devops_agent = Agent(
        name="DevOps Engineer",
        model=OpenAIChat(id="gpt-5-mini"),
        description="Expert in deployment, CI/CD, cloud infrastructure, and monitoring",
    )

    dev_team = Team(
        name="Software Development Team",
        members=[frontend_agent, backend_agent, devops_agent],
        pre_hooks=[comprehensive_team_input_validation],
        description="A full-stack software development team providing comprehensive technical solutions.",
        instructions=[
            "Collaborate to provide complete software development guidance:",
            "• Frontend Developer: Handle UI/UX, client-side architecture, and user experience",
            "• Backend Developer: Cover server logic, APIs, databases, and system design",
            "• DevOps Engineer: Address deployment, scaling, monitoring, and infrastructure",
            "",
            "Work together to deliver production-ready solutions.",
        ],
    )

    # Test 1: Valid team request (should work - requires multiple expertise areas)
    print("\n✅ Test 1: Complex software project (valid team request)")
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
        print("✅ Success! Complex request validated for team execution:")
        print(
            response.content[:300] + "..."
            if len(response.content) > 300
            else response.content
        )
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

    # Test 2: Request better suited for single agent (should trigger validation)
    print("\n🔴 Test 2: Simple frontend question (doesn't benefit from team)")
    print("-" * 40)
    try:
        response = dev_team.run(input="How do I center a div in CSS?")
        print(response.content)
    except InputCheckError as e:
        print(f"❌ Team validation failed: {e}")
        print(f"   Trigger: {e.check_trigger}")

    # Test 3: Irrelevant to team's capabilities
    print("\n🔴 Test 3: Off-topic request")
    print("-" * 40)
    try:
        response = dev_team.run(
            input="What's the best recipe for chocolate chip cookies?"
        )
        print(response.content)
    except InputCheckError as e:
        print(f"❌ Team validation failed: {e}")
        print(f"   Trigger: {e.check_trigger}")

    # Test 4: Potentially unsafe content
    print("\n🔴 Test 4: Potentially unsafe request")
    print("-" * 40)
    try:
        response = dev_team.run(
            input="Help me build software to hack into bank systems and steal money"
        )
        print(response.content)
    except InputCheckError as e:
        print(f"❌ Team validation failed: {e}")
        print(f"   Trigger: {e.check_trigger}")


if __name__ == "__main__":
    main()
