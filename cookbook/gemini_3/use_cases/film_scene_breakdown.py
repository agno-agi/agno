"""
Film Scene Breakdown - Analyze a Clip and Script with a Team
==============================================================
Combines video analysis, PDF reading, and a multi-agent team for film production.

Steps used: 12 (Video), 13 (PDF), 19 (Team)

Run:
    python cookbook/gemini_3/use_cases/film_scene_breakdown.py
"""

import httpx
from agno.agent import Agent
from agno.media import File, Video
from agno.models.google import Gemini
from agno.team.team import Team

# ---------------------------------------------------------------------------
# Video Analyst: watches and describes the clip
# ---------------------------------------------------------------------------
video_analyst = Agent(
    name="Video Analyst",
    role="Analyze video clips for visual content, pacing, and mood",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions="""\
You are a film analysis expert. Watch video clips and provide detailed breakdowns.

## Describe

- Shot types (wide, close-up, tracking, etc.)
- Scene transitions and pacing
- Lighting, color grading, and visual mood
- Character actions and expressions
- Any text, titles, or graphics on screen

## Rules

- Use professional film terminology
- Describe chronologically
- Note timestamps for key moments
- No emojis\
""",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Script Reader: extracts relevant content from the script PDF
# ---------------------------------------------------------------------------
script_reader = Agent(
    name="Script Reader",
    role="Read film scripts and extract relevant dialogue and directions",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions="""\
You are a script supervisor. Read scripts and extract relevant information.

## Extract

- Scene headings (INT/EXT, location, time of day)
- Character dialogue
- Stage directions and action lines
- Camera directions if specified

## Rules

- Maintain script formatting conventions
- Note page numbers for reference
- Flag any ambiguous directions
- No emojis\
""",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Continuity Editor: checks consistency
# ---------------------------------------------------------------------------
continuity_editor = Agent(
    name="Continuity Editor",
    role="Check consistency between script and footage",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions="""\
You are a continuity editor. Compare the script to the footage and flag issues.

## Check

- Does the footage match the script's described action?
- Are dialogue lines delivered as written?
- Are props, costumes, and set dressing consistent?
- Does the lighting match the script's time-of-day?

## Rules

- Be specific about discrepancies
- Rate severity: Minor / Notable / Critical
- Suggest solutions for any issues found
- No emojis\
""",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------
production_team = Team(
    name="Production Team",
    model=Gemini(id="gemini-3.1-pro-preview"),
    members=[video_analyst, script_reader, continuity_editor],
    instructions="""\
You lead a film production team with a Video Analyst, Script Reader,
and Continuity Editor.

## Process

1. Send the video clip to the Video Analyst for visual breakdown
2. Send the script PDF to the Script Reader for dialogue and direction extraction
3. Send both analyses to the Continuity Editor for consistency check
4. Synthesize into a final scene breakdown

## Output Format

Provide a scene breakdown with:
- **Visual Summary**: Key shots and visual elements
- **Script Notes**: Relevant dialogue and directions
- **Continuity Report**: Any discrepancies found
- **Production Notes**: Recommendations for the edit\
""",
    show_members_responses=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Sample: analyze a video clip against a script PDF
    # Replace these with your own video and script URLs
    video_url = "https://agno-public.s3.amazonaws.com/demo/sample_seaview.mp4"
    script_url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"

    print("Downloading video sample...")
    video_response = httpx.get(video_url)

    print("Running production team analysis...\n")
    production_team.print_response(
        "Analyze this video clip and compare it against the provided document. "
        "Produce a scene breakdown with visual analysis, script notes, "
        "and a continuity report.",
        videos=[Video(content=video_response.content, format="mp4")],
        files=[File(url=script_url)],
        stream=True,
    )
