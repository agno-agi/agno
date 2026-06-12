"""
Tool Based Generative UI — Dojo Demo
=====================================

Frontend tool: generate_haiku (external_execution)

Dojo expects generate_haiku with:
- japanese: List[str] - 3 lines of haiku in Japanese
- english: List[str] - 3 lines translated to English
- image_name: str - One of the valid image names
- gradient: str - CSS gradient for background

Valid image names (from Dojo):
- Osaka_Castle_Turret_Stone_Wall_Pine_Trees_Daytime.jpg
- Tokyo_Skyline_Night_Tokyo_Tower_Mount_Fuji_View.jpg
- Itsukushima_Shrine_Miyajima_Floating_Torii_Gate_Sunset_Long_Exposure.jpg
- Takachiho_Gorge_Waterfall_River_Lush_Greenery_Japan.jpg
- Bonsai_Tree_Potted_Japanese_Art_Green_Foliage.jpeg
- Shirakawa-go_Gassho-zukuri_Thatched_Roof_Village_Aerial_View.jpg
- Ginkaku-ji_Silver_Pavilion_Kyoto_Japanese_Garden_Pond_Reflection.jpg
- Senso-ji_Temple_Asakusa_Cherry_Blossoms_Kimono_Umbrella.jpg
- Cherry_Blossoms_Sakura_Night_View_City_Lights_Japan.jpg
- Mount_Fuji_Lake_Reflection_Cherry_Blossoms_Sakura_Spring.jpg
"""

from typing import List

from agno.agent.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools import tool

VALID_IMAGE_NAMES = [
    "Osaka_Castle_Turret_Stone_Wall_Pine_Trees_Daytime.jpg",
    "Tokyo_Skyline_Night_Tokyo_Tower_Mount_Fuji_View.jpg",
    "Itsukushima_Shrine_Miyajima_Floating_Torii_Gate_Sunset_Long_Exposure.jpg",
    "Takachiho_Gorge_Waterfall_River_Lush_Greenery_Japan.jpg",
    "Bonsai_Tree_Potted_Japanese_Art_Green_Foliage.jpeg",
    "Shirakawa-go_Gassho-zukuri_Thatched_Roof_Village_Aerial_View.jpg",
    "Ginkaku-ji_Silver_Pavilion_Kyoto_Japanese_Garden_Pond_Reflection.jpg",
    "Senso-ji_Temple_Asakusa_Cherry_Blossoms_Kimono_Umbrella.jpg",
    "Cherry_Blossoms_Sakura_Night_View_City_Lights_Japan.jpg",
    "Mount_Fuji_Lake_Reflection_Cherry_Blossoms_Sakura_Spring.jpg",
]


@tool(external_execution=True, external_execution_silent=True)
def generate_haiku(japanese: List[str], english: List[str], image_name: str, gradient: str) -> str:
    """Generate and display a haiku with image and styling.

    Args:
        japanese: 3 lines of haiku in Japanese
        english: 3 lines of haiku translated to English
        image_name: One relevant image name from the valid list
        gradient: CSS gradient color for the background (e.g., "linear-gradient(135deg, #667eea 0%, #764ba2 100%)")
    """
    return "Haiku generated and displayed in frontend"


generative_ui_agent = Agent(
    name="tool_based_generative_ui",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[generate_haiku],
    instructions=f"""You are a haiku poet. When asked to create a haiku:

1. Create a beautiful haiku in both English (5-7-5 syllables) and Japanese
2. Choose a relevant image from: {', '.join(VALID_IMAGE_NAMES)}
3. Choose a beautiful CSS gradient for the background
4. Use the generate_haiku tool with all parameters

Example gradient: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)"

The frontend will render your haiku with the image and gradient as a beautiful card.""",
    markdown=True,
)
