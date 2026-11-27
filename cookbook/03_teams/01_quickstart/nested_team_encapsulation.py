"""
Nested Team Encapsulation
==========================

When a Team contains another Team as a member, by default the parent team's
leader sees the full nested member tree in its system prompt and can delegate
directly to grandchild agents — bypassing the sub-team's own leader.

Set `expose_sub_team_members=False` on the parent team to treat sub-teams as
opaque capabilities. The sub-team appears to the parent as a single unit; the
sub-team's leader handles its own internal delegation.

This example prints the top team's `<team_members>` content under both settings
so the difference is visible without hitting a model.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team


def build_top_team(expose_sub_team_members: bool) -> Team:
    research_agent = Agent(
        name="Research Agent",
        model=OpenAIResponses(id="gpt-5.4"),
        role="Gather references and source material",
    )
    analysis_agent = Agent(
        name="Analysis Agent",
        model=OpenAIResponses(id="gpt-5.4"),
        role="Extract key findings and implications",
    )
    research_team = Team(
        name="Research Team",
        description="Handles gathering and analyzing evidence",
        members=[research_agent, analysis_agent],
        model=OpenAIResponses(id="gpt-5.4"),
    )

    writing_agent = Agent(
        name="Writing Agent",
        model=OpenAIResponses(id="gpt-5.4"),
        role="Draft polished narrative output",
    )
    editing_agent = Agent(
        name="Editing Agent",
        model=OpenAIResponses(id="gpt-5.4"),
        role="Improve clarity and structure",
    )
    writing_team = Team(
        name="Writing Team",
        description="Handles drafting and editing the final piece",
        members=[writing_agent, editing_agent],
        model=OpenAIResponses(id="gpt-5.4"),
    )

    return Team(
        name="Program Team",
        members=[research_team, writing_team],
        model=OpenAIResponses(id="gpt-5.4"),
        expose_sub_team_members=expose_sub_team_members,
    )


if __name__ == "__main__":
    print("--- expose_sub_team_members=True (default: nested members visible) ---")
    open_top = build_top_team(expose_sub_team_members=True)
    print(open_top.get_members_system_message_content())

    print("--- expose_sub_team_members=False (sub-teams as opaque capabilities) ---")
    closed_top = build_top_team(expose_sub_team_members=False)
    print(closed_top.get_members_system_message_content())

    # With encapsulation on, the top team must delegate to the sub-team
    # (e.g. member_id="research-team"), and the sub-team's leader decides
    # which of its own members to use. Trying to delegate directly to a
    # grandchild like "research-agent" from the top team is rejected.
    print("--- find 'research-agent' from the closed top team ---")
    print(closed_top._find_member_by_id("research-agent"))
