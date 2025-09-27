"""
Example demonstrating output validation using post-hooks with Agno Teams.

This example shows how to:
1. Validate team responses for quality, coordination, and completeness
2. Ensure team outputs meet collaboration standards
3. Check for consistency between team member contributions
4. Raise OutputCheckError when team validation fails
"""

import asyncio

from agno.agent import Agent
from agno.exceptions import CheckTrigger, OutputCheckError
from agno.models.openai import OpenAIChat
from agno.run.team import TeamRunOutput
from agno.team import Team
from pydantic import BaseModel


class TeamOutputValidationResult(BaseModel):
    is_comprehensive: bool
    shows_collaboration: bool
    is_consistent: bool
    is_professional: bool
    is_safe: bool
    concerns: list[str]
    confidence_score: float


def validate_team_response_quality(run_output: TeamRunOutput, team: Team) -> None:
    """
    Post-hook: Validate the team's response for quality and collaboration standards.

    This hook checks:
    - Response comprehensiveness (leverages team expertise)
    - Evidence of collaboration between team members
    - Consistency and coherence across different perspectives
    - Professional tone and safety of team content

    Raises OutputCheckError if validation fails.
    """

    # Skip validation for empty responses
    if not run_output.content or len(run_output.content.strip()) < 20:
        raise OutputCheckError(
            "Team response is too short or empty",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )

    # Build team context for validation
    team_context = f"Team '{team.name}' with {len(team.members)} members: "
    team_context += ", ".join(
        [
            f"{member.name} ({getattr(member, 'description', 'No description')})"
            for member in team.members
        ]
    )

    # Create a team validation agent
    validator_agent = Agent(
        name="Team Output Validator",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions=[
            "You are a team output quality validator. Analyze team responses for:",
            "1. COMPREHENSIVENESS: Response leverages multiple team members' expertise effectively",
            "2. COLLABORATION: Evidence that team members worked together vs just individual responses",
            "3. CONSISTENCY: Different perspectives are coherent and don't contradict each other",
            "4. PROFESSIONALISM: Language is professional and appropriate for team communication",
            "5. SAFETY: Content is safe and doesn't contain harmful or conflicting advice",
            "",
            "Provide a confidence score (0.0-1.0) for overall team response quality.",
            "List any specific concerns about team coordination or output quality.",
            "",
            "Teams should add value beyond what individual agents could provide.",
        ],
        output_schema=TeamOutputValidationResult,
    )

    validation_result = validator_agent.run(
        input=f"""
        {team_context}

        Validate this team response: '{run_output.content}'

        Consider:
        - Does it show multiple perspectives working together?
        - Is it more valuable than a single agent response would be?
        - Are the different viewpoints consistent and complementary?
        """
    )

    result = validation_result.content

    # Check validation results and raise errors for failures
    if not result.is_comprehensive:
        raise OutputCheckError(
            f"Team response lacks comprehensiveness. Concerns: {', '.join(result.concerns)}",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )

    if not result.shows_collaboration:
        raise OutputCheckError(
            f"Response doesn't show effective team collaboration. Concerns: {', '.join(result.concerns)}",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )

    if not result.is_consistent:
        raise OutputCheckError(
            f"Team response contains inconsistencies between member perspectives. Concerns: {', '.join(result.concerns)}",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )

    if not result.is_professional:
        raise OutputCheckError(
            f"Team response lacks professional tone. Concerns: {', '.join(result.concerns)}",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )

    if not result.is_safe:
        raise OutputCheckError(
            f"Team response contains potentially unsafe content. Concerns: {', '.join(result.concerns)}",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )

    if result.confidence_score < 0.7:
        raise OutputCheckError(
            f"Team response quality score too low ({result.confidence_score:.2f}). Concerns: {', '.join(result.concerns)}",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )


def simple_team_coordination_check(run_output: TeamRunOutput, team: Team) -> None:
    """
    Simple post-hook: Basic validation for team coordination indicators.

    Ensures team responses show some evidence of multi-member input.
    """
    content = run_output.content.strip() if run_output.content else ""

    # Check for basic team coordination indicators
    team_indicators = [
        "we recommend",
        "our analysis",
        "team",
        "collectively",
        "different perspectives",
        "combined",
        "consensus",
        "coordinate",
    ]

    # Check if response mentions multiple team members or shows collaboration
    member_mentions = sum(
        1 for member in team.members if member.name.lower() in content.lower()
    )
    has_team_language = any(
        indicator in content.lower() for indicator in team_indicators
    )

    if not has_team_language and member_mentions < 2:
        raise OutputCheckError(
            "Response doesn't show evidence of team collaboration or multiple perspectives",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )

    if len(content) < 100:
        raise OutputCheckError(
            "Team response is too brief to demonstrate collaborative value",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )


async def main():
    """Demonstrate output validation post-hooks for teams."""
    print("🔍 Team Output Validation Post-Hook Examples")
    print("=" * 60)

    # Team with comprehensive output validation
    team_with_validation = Team(
        name="Legal Advisory Team",
        members=[
            Agent(
                name="Corporate Lawyer",
                model=OpenAIChat(id="gpt-4o-mini"),
                description="Expert in corporate law, contracts, and compliance",
            ),
            Agent(
                name="Tax Attorney",
                model=OpenAIChat(id="gpt-4o-mini"),
                description="Specialist in tax law, regulations, and planning",
            ),
            Agent(
                name="Risk Analyst",
                model=OpenAIChat(id="gpt-4o-mini"),
                description="Expert in legal risk assessment and mitigation",
            ),
        ],
        post_hooks=[validate_team_response_quality],
        instructions=[
            "Collaborate to provide comprehensive legal guidance:",
            "• Corporate Lawyer: Address legal structure, compliance, and contracts",
            "• Tax Attorney: Cover tax implications and optimization strategies",
            "• Risk Analyst: Identify and assess legal risks and mitigation approaches",
            "",
            "Work together to provide coordinated legal advice that leverages all expertise areas.",
        ],
    )

    # Team with simple validation only
    team_simple = Team(
        name="Content Creation Team",
        members=[
            Agent(name="Writer", model=OpenAIChat(id="gpt-4o-mini")),
            Agent(name="Editor", model=OpenAIChat(id="gpt-4o-mini")),
        ],
        post_hooks=[simple_team_coordination_check],
        instructions=[
            "Collaborate to create high-quality content with proper writing and editing coordination."
        ],
    )

    # Test 1: Well-coordinated team response (should pass validation)
    print("\n✅ Test 1: Well-coordinated legal team response")
    print("-" * 40)
    try:
        await team_with_validation.aprint_response(
            input="""
            We're starting a tech startup and need to understand the legal structure options.
            We're considering LLC vs C-Corp, have tax implications to consider, and want to
            minimize legal risks while allowing for future investment rounds.

            Please provide comprehensive guidance covering corporate structure, tax considerations, and risk management.
            """
        )
        print("✅ Team response passed validation")
    except OutputCheckError as e:
        print(f"❌ Validation failed: {e}")
        print(f"   Trigger: {e.check_trigger}")

    # Test 2: Force a poorly coordinated response (should fail validation)
    print("\n❌ Test 2: Poorly coordinated team response")
    print("-" * 40)

    # Create a team that might not coordinate well
    poor_coordination_team = Team(
        name="Unfocused Team",
        members=[
            Agent(
                name="Agent1",
                model=OpenAIChat(id="gpt-4o-mini"),
                instructions=[
                    "Give brief, individual responses without considering teammates."
                ],
            ),
            Agent(
                name="Agent2",
                model=OpenAIChat(id="gpt-4o-mini"),
                instructions=["Provide minimal responses without team coordination."],
            ),
        ],
        post_hooks=[validate_team_response_quality],
        instructions=["Just answer the question quickly without much coordination."],
    )

    try:
        await poor_coordination_team.aprint_response(input="What's 2+2?")
    except OutputCheckError as e:
        print(f"❌ Team validation failed as expected: {e}")
        print(f"   Trigger: {e.check_trigger}")

    # Test 3: Normal response with simple validation
    print("\n✅ Test 3: Normal response with simple team validation")
    print("-" * 40)
    try:
        await team_simple.aprint_response(
            input="Create a blog post about the benefits of remote work, ensuring it's well-written and properly edited."
        )
        print("✅ Response passed simple team validation")
    except OutputCheckError as e:
        print(f"❌ Validation failed: {e}")
        print(f"   Trigger: {e.check_trigger}")


if __name__ == "__main__":
    asyncio.run(main())
