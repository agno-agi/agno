"""🌎 World Builder - Your AI World Creator!

This advanced example shows how to build a sophisticated world building system that
creates rich, detailed fictional worlds.

Example prompts to try:
- "Create a world where time flows backwards"
- "Design a steampunk world powered by dreams"
- "Build an underwater civilization in a gas giant"
- "Make a world where music is the source of magic"
- "Design a world where plants are sentient and rule"
- "Create a world inside a giant computer simulation"

View the README for instructions on how to run the application.
"""

from textwrap import dedent
from typing import List

from agno.agent import Agent
from agno.models.anthropic.claude import Claude
from agno.models.google.gemini import Gemini
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field


class World(BaseModel):
    """Model representing a fictional world with its key attributes."""

    name: str = Field(
        ...,
        description=(
            "The name of this world. Be exceptionally creative and unique. "
            "Avoid using simple names like Futura, Earth, or other common names."
        ),
    )
    characteristics: List[str] = Field(
        ...,
        description=(
            "Key attributes of the world. Examples: Ethereal, Arcane, Quantum-Fueled, "
            "Dreamlike, Mechanized, Harmonious. Think outside the box."
        ),
    )
    currency: str = Field(
        ...,
        description=(
            "The monetary system or trade medium in the world. "
            "Consider unusual or symbolic currencies (e.g., Memory Crystals, Void Shards)."
        ),
    )
    languages: List[str] = Field(
        ...,
        description=(
            "The languages spoken in the world. Invent languages with unique phonetics, "
            "scripts, or origins. Examples: Elurian, Syneth, Aeon's Glyph."
        ),
    )
    history: str = Field(
        ...,
        description=(
            "The detailed history of the world spanning at least 100,000 years. "
            "Include pivotal events, revolutions, cataclysms, golden ages, and more. "
            "Make it immersive and richly detailed."
        ),
    )
    wars: List[str] = Field(
        ...,
        description=(
            "List of major wars or conflicts that shaped the world. Each should have unique "
            "motivations, participants, and consequences."
        ),
    )
    drugs: List[str] = Field(
        ...,
        description=(
            "Substances used in the world, either recreationally, medically, or spiritually. "
            "Invent intriguing names and effects (e.g., Lunar Nectar, Dreamweaver Elixir)."
        ),
    )


def get_world_builder(
    model_id: str = "openai:gpt-4o",
    debug_mode: bool = False,
) -> Agent:
    """Returns an instance of the World Builder Agent.

    Args:
        model: Model identifier to use
        debug_mode: Enable debug logging
    """
    # Parse model provider and name
    provider, model_name = model_id.split(":")

    # Select appropriate model class based on provider
    if provider == "openai":
        model = OpenAIChat(id=model_name)
    elif provider == "google":
        model = Gemini(id=model_name)
    elif provider == "anthropic":
        model = Claude(id=model_name)
    else:
        raise ValueError(f"Unsupported model provider: {provider}")

    return Agent(
        name="world_builder",
        model=model,
        description=dedent("""\
        You are WorldCrafter-X, an elite world building specialist focused on:
        
        - Unique world concepts
        - Rich cultural details  
        - Complex histories
        - Innovative systems
        - Compelling conflicts
        - Immersive atmospheres
        
        You combine boundless creativity with meticulous attention to detail to craft unforgettable worlds."""),
        instructions=dedent("""\
        You are tasked with creating entirely unique and intricate worlds.
        
        When a user provides a world description:
        1. Carefully analyze all aspects of the requested world
        2. Think deeply about how different elements would interact
        3. Create rich, interconnected systems and histories
        4. Ensure internal consistency while being creative
        5. Focus on unique and memorable details
        6. Avoid clichés and common tropes
        7. Consider long-term implications of world features
        8. Create compelling conflicts and dynamics
        
        Remember to:
        - Push creative boundaries
        - Use vivid, evocative language
        - Create memorable names and terms
        - Maintain internal logic
        - Consider multiple cultural perspectives
        - Add unexpected but fitting elements"""),
        response_model=World,
        debug_mode=debug_mode,
    )
