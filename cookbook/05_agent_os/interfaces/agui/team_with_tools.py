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
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.agui.agui import AGUI
from agno.team.team import Team
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------


@tool(external_execution=True, external_execution_silent=True)
def generate_haiku(english: List[str], japanese: List[str], image_name: str, gradient: str) -> str:
    """Generate a haiku in Japanese and English and display it in the frontend.

    Schema matches the AG-UI dojo's ``tool_based_generative_ui`` page so
    the frontend's React render handler can pick up every field:
      * ``english``   - 3 English lines of the haiku.
      * ``japanese``  - 3 Japanese (kanji) lines of the haiku.
      * ``image_name`` - One filename string from the dojo's curated set
        of Japanese landscape images (e.g.
        ``Takachiho_Gorge_Waterfall_River_Lush_Greenery_Japan.jpg``).
      * ``gradient``  - A CSS gradient string used as the card background.

    Marked ``external_execution_silent=True`` so the AG-UI client does not
    see a "Team run paused. The following require input:" status message
    while the tool is executing. The frontend handler does the work.
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
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[generate_haiku],
    description="A team that generates haikus on request using a frontend tool.",
    instructions="""
    When the user asks for a haiku, you MUST call the generate_haiku tool
    directly with all four arguments:
      * english        - exactly 3 English lines.
      * japanese       - exactly 3 Japanese (kanji) lines.
      * image_name     - ONE filename chosen from the list below. Match
        the haiku's THEME to the image. Do NOT default to the same image
        every call.
      * gradient       - a CSS linear-gradient string whose colours
        complement the chosen image and theme (sunsets warm, oceans cool,
        spring pastel, night dark, etc.).

    Valid image_name values and the theme each one fits best:
      * "Osaka_Castle_Turret_Stone_Wall_Pine_Trees_Daytime.jpg"
        -> castle, history, stone, daytime, pine
      * "Tokyo_Skyline_Night_Tokyo_Tower_Mount_Fuji_View.jpg"
        -> city, urban, night, lights, modern
      * "Itsukushima_Shrine_Miyajima_Floating_Torii_Gate_Sunset_Long_Exposure.jpg"
        -> ocean, sea, water, sunset, torii, shrine
      * "Takachiho_Gorge_Waterfall_River_Lush_Greenery_Japan.jpg"
        -> forest, waterfall, river, green, nature
      * "Bonsai_Tree_Potted_Japanese_Art_Green_Foliage.jpeg"
        -> bonsai, art, miniature, foliage, zen
      * "Shirakawa-go_Gassho-zukuri_Thatched_Roof_Village_Aerial_View.jpg"
        -> rural, village, traditional, snow, winter
      * "Ginkaku-ji_Silver_Pavilion_Kyoto_Japanese_Garden_Pond_Reflection.jpg"
        -> garden, zen, pond, reflection, kyoto
      * "Senso-ji_Temple_Asakusa_Cherry_Blossoms_Kimono_Umbrella.jpg"
        -> temple, kimono, cherry blossoms, cultural
      * "Cherry_Blossoms_Sakura_Night_View_City_Lights_Japan.jpg"
        -> sakura, spring, night, city, lights
      * "Mount_Fuji_Lake_Reflection_Cherry_Blossoms_Sakura_Spring.jpg"
        -> mount fuji, mountain, lake, spring, sakura

    Do not write the haiku as plain text. Do not delegate to members.
    """,
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
