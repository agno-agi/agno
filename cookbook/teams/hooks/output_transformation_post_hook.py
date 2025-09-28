"""
Example demonstrating output transformation using post-hooks with Agno Teams.

This example shows how to:
1. Transform team responses by updating TeamRunOutput.content
2. Add team-specific formatting, coordination summaries, and structure
3. Enhance collaboration visibility and response organization
4. Aggregate insights from multiple team members
"""

from datetime import datetime

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.team import TeamRunOutput
from agno.team import Team
from pydantic import BaseModel


class FormattedTeamResponse(BaseModel):
    executive_summary: str
    member_contributions: dict[str, str]  # member_name -> their key contribution
    key_insights: list[str]
    action_items: list[str]
    coordination_notes: str
    disclaimer: str


def add_team_metadata(run_output: TeamRunOutput, team: Team) -> None:
    """
    Simple post-hook: Add team metadata and basic formatting to responses.

    Shows which team members participated and adds timestamp.
    """
    content = run_output.content.strip() if run_output.content else ""

    team_members = [member.name for member in team.members]

    # Add team metadata for transparency
    formatted_content = f"""# {team.name} Response

{content}

---
**Team Members:** {", ".join(team_members)}  
**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}"""

    run_output.content = formatted_content


def add_collaboration_summary(run_output: TeamRunOutput, team: Team) -> None:
    """
    Advanced post-hook: Add collaboration summary showing individual contributions.

    Analyzes member responses to highlight unique contributions.
    """
    content = run_output.content.strip() if run_output.content else ""

    # Extract individual member responses if available
    member_summaries = []
    if hasattr(run_output, "member_responses") and run_output.member_responses:
        for i, member_response in enumerate(run_output.member_responses):
            member_name = (
                team.members[i].name if i < len(team.members) else f"Member {i + 1}"
            )
            if hasattr(member_response, "content") and member_response.content:
                # Truncate long responses for summary
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
    """
    Comprehensive post-hook: Structure team responses with AI-powered organization.

    Uses an AI agent to organize the team response into a clear format
    showing executive summary, individual contributions, and action items.
    """

    # Create a team response formatter
    formatter_agent = Agent(
        name="Team Response Formatter",
        model=OpenAIChat(id="gpt-4o-mini"),
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
        # Prepare context about the team
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

        # Build comprehensive team response
        enhanced_response = f"""# {team.name} - Collaborative Response

## Executive Summary
{formatted.executive_summary}

## Team Member Contributions
{chr(10).join([f"### {member}: {contribution}" for member, contribution in formatted.member_contributions.items()])}

## Key Insights
{chr(10).join([f"• {insight}" for insight in formatted.key_insights])}

## Recommended Actions
{chr(10).join([f"{i + 1}. {action}" for i, action in enumerate(formatted.action_items)])}

## Team Coordination
{formatted.coordination_notes}

## Important Notice
{formatted.disclaimer}

---
**Team:** {team.name} ({len(team.members)} members)  
**Formatted:** {datetime.now().strftime("%Y-%m-%d at %H:%M:%S")}"""

        # Update the team output with enhanced response
        run_output.content = enhanced_response

    except Exception as e:
        # Fallback to collaboration summary if AI formatting fails
        print(
            f"Warning: Advanced team formatting failed ({e}), using collaboration summary"
        )
        add_collaboration_summary(run_output, team)


def main():
    """Demonstrate output transformation post-hooks for teams."""
    print("🎨 Team Output Transformation Post-Hook Examples")
    print("=" * 60)

    # Test 1: Simple team metadata formatting
    print("\n📝 Test 1: Basic team metadata transformation")
    print("-" * 50)

    # Create simple team
    analyst_agent = Agent(
        name="Market Analyst",
        model=OpenAIChat(id="gpt-5-mini"),
        description="Expert in market trends and competitive analysis",
    )

    advisor_agent = Agent(
        name="Business Advisor",
        model=OpenAIChat(id="gpt-5-mini"),
        description="Specialist in business strategy and operations",
    )

    metadata_team = Team(
        name="Business Intelligence Team",
        model=OpenAIChat(id="gpt-5-mini"),
        members=[analyst_agent, advisor_agent],
        post_hooks=[add_team_metadata],
        instructions=[
            "Provide comprehensive business insights combining market analysis and strategic advice."
        ],
    )

    metadata_team.print_response(
        input="What are the key trends in the e-commerce industry for 2024?"
    )
    print("✅ Response with team metadata formatting")

    # Test 2: Collaboration summary
    print("\n🤝 Test 2: Collaboration summary transformation")
    print("-" * 50)

    collab_team = Team(
        name="Product Development Team",
        members=[
            Agent(
                name="UX Designer",
                model=OpenAIChat(id="gpt-5-mini"),
                description="User experience and interface design expert",
            ),
            Agent(
                name="Product Manager",
                model=OpenAIChat(id="gpt-5-mini"),
                description="Product strategy and roadmap specialist",
            ),
            Agent(
                name="Engineer",
                model=OpenAIChat(id="gpt-5-mini"),
                description="Technical implementation and architecture expert",
            ),
        ],
        post_hooks=[add_collaboration_summary],
        instructions=[
            "Collaborate to provide comprehensive product development guidance:",
            "• UX Designer: Focus on user experience and design considerations",
            "• Product Manager: Address strategy, features, and market fit",
            "• Engineer: Cover technical feasibility and implementation",
        ],
    )

    collab_team.print_response(
        input="How should we approach building a mobile app for fitness tracking? Give me a detailed plan."
    )
    print("✅ Response with collaboration summary")

    # Test 3: Comprehensive structured team response
    print("\n🏗️  Test 3: Comprehensive structured team response")
    print("-" * 50)

    consulting_team = Team(
        name="Management Consulting Team",
        members=[
            Agent(
                name="Strategy Consultant",
                model=OpenAIChat(id="gpt-5-mini"),
                description="Business strategy and planning expert",
            ),
            Agent(
                name="Operations Specialist",
                model=OpenAIChat(id="gpt-5-mini"),
                description="Process optimization and efficiency expert",
            ),
            Agent(
                name="Change Management Expert",
                model=OpenAIChat(id="gpt-5-mini"),
                description="Organizational change and transformation specialist",
            ),
        ],
        post_hooks=[structure_team_response],
        instructions=[
            "Provide comprehensive management consulting advice:",
            "• Strategy Consultant: Define strategic direction and competitive positioning",
            "• Operations Specialist: Identify operational improvements and efficiencies",
            "• Change Management Expert: Address organizational and cultural considerations",
            "",
            "Work together to deliver actionable transformation guidance.",
        ],
    )

    consulting_team.print_response(
        input="Our mid-size manufacturing company wants to implement digital transformation. We have 500 employees and are struggling with outdated processes and resistance to change. What's our path forward?"
    )
    print("✅ Comprehensive structured team response")


if __name__ == "__main__":
    main()
