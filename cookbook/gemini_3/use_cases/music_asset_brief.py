"""
Music Asset Brief - Analyze a Track and Produce a Brief
=========================================================
Combines audio analysis, image understanding, web search, and structured output for a music brief.

Steps used: 2 (Tools), 3 (Structured Output), 8 (Image), 10 (Audio)

Run:
    python cookbook/gemini_3/use_cases/music_asset_brief.py
"""

from typing import List

import httpx
from agno.agent import Agent
from agno.media import Audio, Image
from agno.models.google import Gemini
from agno.tools.websearch import WebSearchTools
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Output Schema
# ---------------------------------------------------------------------------
class TrackBrief(BaseModel):
    track_name: str = Field(..., description="Name of the track")
    artist: str = Field(..., description="Artist or band name")
    genre: str = Field(..., description="Primary genre")
    mood: str = Field(..., description="Overall mood (e.g., energetic, melancholic)")
    tempo_estimate: str = Field(..., description="Estimated tempo (slow, mid, fast)")
    visual_style: str = Field(..., description="Visual style of the artwork")
    target_audience: str = Field(..., description="Suggested target audience")
    marketing_angles: List[str] = Field(..., description="3-5 marketing angles")
    comparable_artists: List[str] = Field(..., description="2-3 comparable artists")
    summary: str = Field(..., description="One-paragraph executive summary")


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a music industry analyst. You analyze tracks, artwork, and market
context to produce comprehensive asset briefs for A&R and marketing teams.

## Workflow

1. If audio is provided, analyze the track: genre, mood, tempo, production style
2. If an image is provided, analyze the artwork: visual style, themes, color palette
3. Search the web for the artist and current market context
4. Produce a structured brief combining all insights

## Rules

- Be specific about genre (not just "pop", say "synth-pop" or "indie pop")
- Name comparable artists that are currently relevant
- Marketing angles should be actionable
- No emojis\
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
music_analyst = Agent(
    name="Music Analyst",
    model=Gemini(id="gemini-3-flash-preview"),
    instructions=instructions,
    tools=[WebSearchTools()],
    output_schema=TrackBrief,
    add_datetime_to_context=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Sample: analyze a track with audio and artwork
    # Replace these with your own audio URL and artwork URL
    audio_url = "https://agno-public.s3.amazonaws.com/demo/sample-audio.mp3"
    artwork_url = "https://agno-public.s3.amazonaws.com/images/krakow_mariacki.jpg"

    print("Downloading audio sample...")
    audio_response = httpx.get(audio_url)

    print("Analyzing track and artwork...\n")
    result = music_analyst.run(
        "Analyze this music track and album artwork. "
        "Research the artist and produce a comprehensive asset brief.",
        audio=[Audio(content=audio_response.content, format="mp3")],
        images=[Image(url=artwork_url)],
    )

    brief: TrackBrief = result.content
    print(f"Track: {brief.track_name} by {brief.artist}")
    print(f"Genre: {brief.genre} | Mood: {brief.mood} | Tempo: {brief.tempo_estimate}")
    print(f"Visual Style: {brief.visual_style}")
    print(f"Target Audience: {brief.target_audience}")
    print("\nMarketing Angles:")
    for angle in brief.marketing_angles:
        print(f"  - {angle}")
    print(f"\nComparable Artists: {', '.join(brief.comparable_artists)}")
    print(f"\nSummary: {brief.summary}")
