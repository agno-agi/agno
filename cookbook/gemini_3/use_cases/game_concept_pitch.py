"""
Game Concept Pitch - Generate Art and Structure a Pitch
=========================================================
Combines image generation, structured output, and a multi-agent team for a game pitch.

Steps used: 3 (Structured Output), 9 (Image Generation), 19 (Team)

Run:
    python cookbook/gemini_3/use_cases/game_concept_pitch.py
"""

from io import BytesIO
from pathlib import Path
from typing import List

from agno.agent import Agent, RunOutput
from agno.models.google import Gemini
from agno.team.team import Team
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
WORKSPACE = Path(__file__).parent.parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Output Schema for Game Pitch
# ---------------------------------------------------------------------------
class GamePitch(BaseModel):
    title: str = Field(..., description="Game title")
    tagline: str = Field(..., description="One-line hook (max 15 words)")
    genre: str = Field(
        ..., description="Primary genre (e.g., action RPG, puzzle platformer)"
    )
    platform: List[str] = Field(..., description="Target platforms")
    target_audience: str = Field(..., description="Target demographic")
    core_mechanic: str = Field(..., description="The one thing that makes the game fun")
    setting: str = Field(
        ..., description="World and setting description (2-3 sentences)"
    )
    unique_selling_points: List[str] = Field(
        ..., description="3-5 unique selling points"
    )
    comparable_titles: List[str] = Field(..., description="2-3 comparable games")
    monetization: str = Field(..., description="Monetization strategy")
    elevator_pitch: str = Field(..., description="Full elevator pitch (one paragraph)")


# ---------------------------------------------------------------------------
# Concept Art Agent (image generation)
# ---------------------------------------------------------------------------
art_agent = Agent(
    name="Concept Artist",
    model=Gemini(
        id="gemini-3-flash-preview",
        response_modalities=["Text", "Image"],
    ),
)

# ---------------------------------------------------------------------------
# Pitch Writer Agent (structured output)
# ---------------------------------------------------------------------------
pitch_writer = Agent(
    name="Pitch Writer",
    role="Write structured game concept pitches",
    model=Gemini(id="gemini-3.1-pro-preview"),
    instructions="""\
You are a game design consultant. Create compelling, structured game pitches.

## Rules

- Be specific about mechanics, not vague
- Comparable titles should be recent (last 3 years)
- Monetization must be realistic for the genre
- The tagline should make someone want to hear more
- No emojis\
""",
    output_schema=GamePitch,
    add_datetime_to_context=True,
)

# ---------------------------------------------------------------------------
# Review Team
# ---------------------------------------------------------------------------
market_analyst = Agent(
    name="Market Analyst",
    role="Evaluate market viability and competitive landscape",
    model=Gemini(id="gemini-3-flash-preview", search=True),
    instructions="""\
You analyze game market trends. Evaluate pitches for market viability.

## Evaluate

- Is there market demand for this genre?
- How crowded is the competitive space?
- Is the monetization realistic?
- What's the risk/reward profile?

## Rules

- Use recent market data
- Be honest about risks
- Suggest specific improvements
- No emojis\
""",
    add_datetime_to_context=True,
)

creative_director = Agent(
    name="Creative Director",
    role="Evaluate creative vision and player experience",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions="""\
You evaluate game concepts for creative quality and player appeal.

## Evaluate

- Is the core mechanic fun and original?
- Does the setting support the gameplay?
- Will the target audience connect with this?
- What's the "wow factor"?

## Rules

- Focus on player experience
- Suggest improvements, not just criticism
- Consider accessibility
- No emojis\
""",
)

review_team = Team(
    name="Review Board",
    model=Gemini(id="gemini-3.1-pro-preview"),
    members=[market_analyst, creative_director],
    instructions="""\
You chair a game pitch review board with a Market Analyst and Creative Director.

## Process

1. Send the pitch to the Market Analyst for viability assessment
2. Send the pitch to the Creative Director for creative evaluation
3. Synthesize into a final review with:
   - **Market Assessment**: Viability and competitive analysis
   - **Creative Review**: Strengths and areas for improvement
   - **Final Verdict**: Go / Revise / Pass with reasoning\
""",
    show_members_responses=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    game_idea = (
        "A cozy underwater exploration game where you play as a marine biologist "
        "discovering and cataloging bioluminescent deep-sea creatures. "
        "The core loop is diving, photographing creatures, and building "
        "a living encyclopedia that other players can browse."
    )

    # Step 1: Generate concept art
    print("Generating concept art...\n")
    art_result = art_agent.run(
        f"Create concept art for this game: {game_idea}. "
        "Show a diver exploring a bioluminescent underwater cave with glowing creatures."
    )

    if art_result and isinstance(art_result, RunOutput) and art_result.images:
        try:
            from PIL import Image as PILImage

            for i, img in enumerate(art_result.images):
                if img.content:
                    image = PILImage.open(BytesIO(img.content))
                    path = WORKSPACE / f"game_concept_{i}.png"
                    image.save(str(path))
                    print(f"Saved concept art to {path}")
        except ImportError:
            print("Install Pillow to save images: pip install Pillow")

    # Step 2: Structure the pitch
    print("\nWriting game pitch...\n")
    pitch_result = pitch_writer.run(f"Create a structured game pitch for: {game_idea}")

    pitch: GamePitch = pitch_result.content
    print(f"Title: {pitch.title}")
    print(f"Tagline: {pitch.tagline}")
    print(f"Genre: {pitch.genre}")
    print(f"Core Mechanic: {pitch.core_mechanic}")
    print(f"\nElevator Pitch: {pitch.elevator_pitch}")

    # Step 3: Review the pitch
    print("\n\nRunning review board...\n")
    review_team.print_response(
        f"Review this game pitch:\n\n"
        f"Title: {pitch.title}\n"
        f"Genre: {pitch.genre}\n"
        f"Platforms: {', '.join(pitch.platform)}\n"
        f"Target Audience: {pitch.target_audience}\n"
        f"Core Mechanic: {pitch.core_mechanic}\n"
        f"Setting: {pitch.setting}\n"
        f"USPs: {', '.join(pitch.unique_selling_points)}\n"
        f"Comparable Titles: {', '.join(pitch.comparable_titles)}\n"
        f"Monetization: {pitch.monetization}\n"
        f"Elevator Pitch: {pitch.elevator_pitch}",
        stream=True,
    )
