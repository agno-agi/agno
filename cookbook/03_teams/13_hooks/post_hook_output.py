"""
Post Hook Output
=============================

Demonstrates output validation and transformation post-hooks for team runs.
"""

import asyncio
from datetime import datetime

from agno.agent import Agent
from agno.exceptions import CheckTrigger, OutputCheckError
from agno.models.openai import OpenAIResponses
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


class FormattedTeamResponse(BaseModel):
    executive_summary: str
    member_contributions: dict[str, str]
    key_insights: list[str]
    action_items: list[str]
    coordination_notes: str
    disclaimer: str


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
def validate_team_response_quality(run_output: TeamRunOutput, team: Team) -> None:
    """Validate team output quality and collaboration consistency."""

    if not run_output.content or len(run_output.content.strip()) < 20:
        raise OutputCheckError(
            "Team response is too short or empty",
            check_trigger=CheckTrigger.OUTPUT_NOT_ALLOWED,
        )

    team_context = f"Team '{team.name}' with {len(team.members)} members: "
    team_context += ", ".join(
        [
            f"{member.name} ({getattr(member, 'description', 'No description')})"
            for member in team.members
        ]
    )

    validator_agent = Agent(
        name="Team Output Validator",
        model=OpenAIResponses(id="gpt-5.2"),
        instructions=[
            "You are a team output quality validator. Analyze team responses for:",
            "1. COMPREHENSIVENESS: Response covers multiple areas of expertise relevant to the question",
            "2. COLLABORATION: Response integrates multiple perspectives into a coherent answer.",
            "   A well-synthesized unified response DOES count as collaboration - it does NOT need explicit member attribution or handoffs.",
            "   If the response covers topics from different domains (e.g. legal, tax, risk), that shows collaboration.",
            "3. CONSISTENCY: Different perspectives are coherent and don't contradict each other",
            "4. PROFESSIONALISM: Language is professional and appropriate",
            "5. SAFETY: Content is safe and doesn't contain harmful advice",
            "",
            "Provide a confidence score (0.0-1.0) for overall quality.",
            "List any specific concerns.",
            "",
            "Be lenient - a comprehensive, multi-perspective response should pass even if it reads as a unified document.",
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
    """Apply lightweight checks for evidence of team collaboration."""
    content = run_output.content.strip() if run_output.content else ""

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


def add_team_metadata(run_output: TeamRunOutput, team: Team) -> None:
    """Add team metadata to output for transparency."""
    content = run_output.content.strip() if run_output.content else ""

    team_members = [member.name for member in team.members]
    formatted_content = f"""# {team.name} Response

{content}

---
**Team Members:** {", ".join(team_members)}
**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}"""

    run_output.content = formatted_content


def add_collaboration_summary(run_output: TeamRunOutput, team: Team) -> None:
    """Append a collaboration summary with per-member highlights."""
    content = run_output.content.strip() if run_output.content else ""

    member_summaries = []
    if hasattr(run_output, "member_responses") and run_output.member_responses:
        for i, member_response in enumerate(run_output.member_responses):
            member_name = (
                team.members[i].name if i < len(team.members) else f"Member {i + 1}"
            )
            if hasattr(member_response, "content") and member_response.content:
                summary = (
                    member_response.content[:200] + "..."
                    if len(member_response.content) > 200
                    else member_response.content
                )
                member_summaries.append(f"**{member_name}:** {summary}")

    enhanced_content = f"""{content}

## Team Collaboration Summary

{chr(10).join(member_summaries) if member_summaries else "Team worked collaboratively on this response."}

---
*Response coordinated by {team.name} • {len(team.members)} team members*
*Generated on {datetime.now().strftime("%B %d, %Y at %I:%M %p")}*"""

    run_output.content = enhanced_content


def structure_team_response(run_output: TeamRunOutput, team: Team) -> None:
    """Reformat output into a structured, action-oriented summary."""
    formatter_agent = Agent(
        name="Team Response Formatter",
        model=OpenAIResponses(id="gpt-5.2"),
        instructions=[
            "You are a team response formatting specialist.",
            "Transform team responses into well-structured formats that highlight:",
            "1. EXECUTIVE_SUMMARY: Clear overview of the team's collective response",
            "2. MEMBER_CONTRIBUTIONS: Identify unique value each team member provided",
            "3. KEY_INSIGHTS: Extract 3-5 most important insights from the team",
            "4. ACTION_ITEMS: Concrete next steps or recommendations",
            "5. COORDINATION_NOTES: How the team members' expertise complemented each other",
            "6. DISCLAIMER: Appropriate disclaimer for the type of advice provided",
            "",
            "Maintain all original information while improving organization and clarity.",
        ],
        output_schema=FormattedTeamResponse,
    )

    try:
        team_context = f"Team '{team.name}' with members: " + ", ".join(
            [
                f"{member.name} ({getattr(member, 'description', 'No description')})"
                for member in team.members
            ]
        )

        formatted_result = formatter_agent.run(
            input=f"""
            {team_context}

            Format this team response: '{run_output.content}'
            """
        )

        formatted = formatted_result.content

        enhanced_response = f"""# {team.name} - Collaborative Response

## Executive Summary
{formatted.executive_summary}

## Team Member Contributions
{chr(10).join([f"### {member}: {contribution}" for member, contribution in formatted.member_contributions.items()])}

## Key Insights
{chr(10).join([f"- {insight}" for insight in formatted.key_insights])}

## Recommended Actions
{chr(10).join([f"{i + 1}. {action}" for i, action in enumerate(formatted.action_items)])}

## Team Coordination
{formatted.coordination_notes}

## Important Notice
{formatted.disclaimer}

---
**Team:** {team.name} ({len(team.members)} members)
**Formatted:** {datetime.now().strftime("%Y-%m-%d at %H:%M:%S")}"""

        run_output.content = enhanced_response

    except Exception as e:
        print(
            f"Warning: Advanced team formatting failed ({e}), using collaboration summary"
        )
        add_collaboration_summary(run_output, team)


# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team_with_validation = Team(
    name="Legal Advisory Team",
    members=[
        Agent(
            name="Corporate Lawyer",
            model=OpenAIResponses(id="gpt-5.2"),
            description="Expert in corporate law, contracts, and compliance",
        ),
        Agent(
            name="Tax Attorney",
            model=OpenAIResponses(id="gpt-5.2"),
            description="Specialist in tax law, regulations, and planning",
        ),
        Agent(
            name="Risk Analyst",
            model=OpenAIResponses(id="gpt-5.2"),
            description="Expert in legal risk assessment and mitigation",
        ),
    ],
    post_hooks=[validate_team_response_quality],
    instructions=[
        "Collaborate to provide comprehensive legal guidance:",
        "Corporate Lawyer: Address legal structure, compliance, and contracts",
        "Tax Attorney: Cover tax implications and optimization strategies",
        "Risk Analyst: Identify and assess legal risks and mitigation approaches",
        "",
        "Work together to provide coordinated legal advice that leverages all expertise areas.",
    ],
)

team_simple = Team(
    name="Content Creation Team",
    members=[
        Agent(name="Writer", model=OpenAIResponses(id="gpt-5.2")),
        Agent(name="Editor", model=OpenAIResponses(id="gpt-5.2")),
    ],
    post_hooks=[simple_team_coordination_check],
    instructions=[
        "Collaborate to create high-quality content with proper writing and editing coordination."
    ],
)

metadata_team = Team(
    name="Business Intelligence Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[
        Agent(
            name="Market Analyst",
            model=OpenAIResponses(id="gpt-5.2"),
            description="Expert in market trends and competitive analysis",
        ),
        Agent(
            name="Business Advisor",
            model=OpenAIResponses(id="gpt-5.2"),
            description="Specialist in business strategy and operations",
        ),
    ],
    post_hooks=[add_team_metadata],
    instructions=[
        "Provide comprehensive business insights combining market analysis and strategic advice."
    ],
)

collab_team = Team(
    name="Product Development Team",
    members=[
        Agent(
            name="UX Designer",
            model=OpenAIResponses(id="gpt-5.2"),
            description="User experience and interface design expert",
        ),
        Agent(
            name="Product Manager",
            model=OpenAIResponses(id="gpt-5.2"),
            description="Product strategy and roadmap specialist",
        ),
        Agent(
            name="Engineer",
            model=OpenAIResponses(id="gpt-5.2"),
            description="Technical implementation and architecture expert",
        ),
    ],
    post_hooks=[add_collaboration_summary],
    instructions=[
        "Collaborate to provide comprehensive product development guidance:",
        "UX Designer: Focus on user experience and design considerations",
        "Product Manager: Address strategy, features, and market fit",
        "Engineer: Cover technical feasibility and implementation",
    ],
)

consulting_team = Team(
    name="Management Consulting Team",
    members=[
        Agent(
            name="Strategy Consultant",
            model=OpenAIResponses(id="gpt-5.2"),
            description="Business strategy and planning expert",
        ),
        Agent(
            name="Operations Specialist",
            model=OpenAIResponses(id="gpt-5.2"),
            description="Process optimization and efficiency expert",
        ),
        Agent(
            name="Change Management Expert",
            model=OpenAIResponses(id="gpt-5.2"),
            description="Organizational change and transformation specialist",
        ),
    ],
    post_hooks=[structure_team_response],
    instructions=[
        "Provide comprehensive management consulting advice:",
        "Strategy Consultant: Define strategic direction and competitive positioning",
        "Operations Specialist: Identify operational improvements and efficiencies",
        "Change Management Expert: Address organizational and cultural considerations",
        "",
        "Work together to deliver actionable transformation guidance.",
    ],
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
async def main() -> None:
    print("Team Output Post-Hook Examples")
    print("=" * 60)

    print("\n[TEST 1] Well-coordinated legal team response")
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
        print("[OK] Team response passed validation")
    except OutputCheckError as e:
        print(f"[ERROR] Validation failed: {e}")
        print(f"   Trigger: {e.check_trigger}")

    print("\n[TEST 2] Poorly coordinated team response")
    print("-" * 40)

    poor_coordination_team = Team(
        name="Unfocused Team",
        members=[
            Agent(
                name="Agent1",
                model=OpenAIResponses(id="gpt-5.2"),
                instructions=[
                    "Give brief, individual responses without considering teammates."
                ],
            ),
            Agent(
                name="Agent2",
                model=OpenAIResponses(id="gpt-5.2"),
                instructions=["Provide minimal responses without team coordination."],
            ),
        ],
        post_hooks=[validate_team_response_quality],
        instructions=["Just answer the question quickly without much coordination."],
    )

    try:
        await poor_coordination_team.aprint_response(input="What's 2+2?")
    except OutputCheckError as e:
        print(f"[ERROR] Team validation failed as expected: {e}")
        print(f"   Trigger: {e.check_trigger}")

    print("\n[TEST 3] Normal response with simple team validation")
    print("-" * 40)
    try:
        await team_simple.aprint_response(
            input="Create a blog post about the benefits of remote work, ensuring it's well-written and properly edited."
        )
        print("[OK] Response passed simple team validation")
    except OutputCheckError as e:
        print(f"[ERROR] Validation failed: {e}")
        print(f"   Trigger: {e.check_trigger}")

    print("\n[TEST 4] Basic team metadata transformation")
    print("-" * 50)
    metadata_team.print_response(
        input="What are the key trends in the e-commerce industry for 2024?"
    )
    print("[OK] Response with team metadata formatting")

    print("\n[TEST 5] Collaboration summary transformation")
    print("-" * 50)
    collab_team.print_response(
        input="How should we approach building a mobile app for fitness tracking? Give me a detailed plan."
    )
    print("[OK] Response with collaboration summary")

    print("\n[TEST 6] Comprehensive structured team response")
    print("-" * 50)
    consulting_team.print_response(
        input="Our mid-size manufacturing company wants to implement digital transformation. We have 500 employees and are struggling with outdated processes and resistance to change. What's our path forward?"
    )
    print("[OK] Comprehensive structured team response")


if __name__ == "__main__":
    asyncio.run(main())
