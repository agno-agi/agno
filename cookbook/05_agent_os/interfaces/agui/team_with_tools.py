"""
Team With Tools
===============

Demonstrates a coordinate-mode Team exposing an external-execution
frontend tool via the AG-UI interface. The team-level tool is registered
with ``external_execution=True`` so the AG-UI client (CopilotKit, the
AG-UI dojo, etc.) is asked to execute it on the user's machine.

This example exercises the Team variants of the AG-UI fixes shipped in
PR #7819:
  * Frontend tool merge (#7801) into the team's tool list via
    ``RunContext.tools``.
  * TeamRunPausedEvent isinstance handling in
    ``_create_completion_events`` so the SSE stream emits
    ``TOOL_CALL_START / ARGS / END`` for the team's external tool.
  * Silent-tool filter in ``_get_team_paused_content`` so AG-UI clients
    don't see a "Team run paused..." text leak.
  * Resume-on-tool-result via ``acontinue_run`` with
    ``RunRequirement(external_execution_result=...)`` correctly set.

Run with:

    .venvs/demo/bin/python cookbook/05_agent_os/interfaces/agui/team_with_tools.py
"""

from typing import List

from agno.agent.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.agui.agui import AGUI
from agno.team.team import Team
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------


@tool(external_execution=True, external_execution_silent=True)
def generate_haiku(
    english: List[str], japanese: List[str], image_name: str, gradient: str
) -> str:
    """Generate a haiku in Japanese and English and display it in the frontend.

    Args:
        english: 3 lines of the haiku translated to English.
        japanese: 3 lines of the haiku in Japanese kanji.
        image_name: One relevant image name from:
            Osaka_Castle_Turret_Stone_Wall_Pine_Trees_Daytime.jpg,
            Tokyo_Skyline_Night_Tokyo_Tower_Mount_Fuji_View.jpg,
            Itsukushima_Shrine_Miyajima_Floating_Torii_Gate_Sunset_Long_Exposure.jpg,
            Takachiho_Gorge_Waterfall_River_Lush_Greenery_Japan.jpg,
            Bonsai_Tree_Potted_Japanese_Art_Green_Foliage.jpeg,
            Shirakawa-go_Gassho-zukuri_Thatched_Roof_Village_Aerial_View.jpg,
            Ginkaku-ji_Silver_Pavilion_Kyoto_Japanese_Garden_Pond_Reflection.jpg,
            Senso-ji_Temple_Asakusa_Cherry_Blossoms_Kimono_Umbrella.jpg,
            Cherry_Blossoms_Sakura_Night_View_City_Lights_Japan.jpg,
            Mount_Fuji_Lake_Reflection_Cherry_Blossoms_Sakura_Spring.jpg.
        gradient: CSS gradient color string for the card background.

    Schema matches the AG-UI dojo's ``tool_based_generative_ui`` page so the
    frontend's React render handler can pick up every field. The
    ``external_execution_silent=True`` flag suppresses the "Team run paused"
    status message while the frontend executes the tool.
    """
    return "Haiku generated and displayed in frontend"


# Member agent. Lightweight — the external tool lives on the team itself
# (the canonical AG-UI Team scenario), not on individual members.
greeter = Agent(
    name="greeter",
    role="Friendly conversational helper",
    model=OpenAIResponses(id="gpt-5.4"),
    instructions="Help with simple conversational tasks. You have no special tools.",
    markdown=True,
)

team = Team(
    name="haiku_team",
    mode="coordinate",
    members=[greeter],
    # In-memory session store so add_history_to_context=True actually has
    # somewhere to persist prior turns. The AG-UI router strips client-sent
    # history (utils.extract_agui_user_input keeps only the last user
    # message), so without a db the team starts fresh on every turn -- the
    # model has no signal it picked image_name='X' before and repeats the
    # same image. InMemoryDb lives for the AgentOS process lifetime;
    # mirrors cookbook/06_storage/in_memory/ and
    # cookbook/03_teams/07_session/share_session_with_agent.py.
    db=InMemoryDb(),
    # gpt-5.4 is the project-standard cookbook model (per CLAUDE.md).
    # As a reasoning model, its explicit reasoning step makes the "do not
    # repeat image_name" rule actually stick -- gpt-4.1-mini and gpt-5.1
    # treated it as a soft suggestion and kept defaulting to the strongest
    # theme association (Takachiho for nature). Reasoning models read the
    # rule, look at the prior turn's tool call in history, and pick a
    # different image. Trade-off: slightly slower responses (reasoning
    # takes time) and temperature is silently ignored.
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[generate_haiku],
    description="A team that generates haikus on request using a frontend tool.",
    # Lightweight prompt: theme hint + readability constraint + soft
    # anti-repeat. Earlier aggressive "CRITICAL diversity rules" with
    # numbered MUST/NEVER directives caused gpt-5.4 to over-think and
    # collapse to the same shade per theme. This shorter prompt lets the
    # reasoning model vary more naturally while still keeping the
    # light-gradient readability requirement.
    instructions=(
        "Help the user write Haikus. When the user asks for a haiku, "
        "call the generate_haiku tool with all four arguments. "
        "Match image_name to the haiku's theme (ocean -> torii or "
        "Mount Fuji Lake; nature -> waterfall, bonsai, or garden; "
        "spring -> cherry blossoms). "
        "Always use LIGHT or MEDIUM-tone gradient colors (pastels like "
        "peach, mint, lavender, soft blue, sunset pink, light yellow) "
        "so the dark haiku text stays clearly readable. Never pick dark "
        "or oversaturated colors. "
        "Vary your choices across consecutive calls -- different "
        "image_name and different gradient hue each time. "
        "Do not delegate to members."
    ),
    add_history_to_context=True,
)


# Setup your AgentOS app
agent_os = AgentOS(
    teams=[team],
    interfaces=[AGUI(team=team)],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Run your AgentOS.

    Configure Dojo / CopilotKit at http://localhost:9002/agui to exercise
    the team-level external-execution flow end to end.
    """
    agent_os.serve(app="team_with_tools:app", port=9002, reload=True)
