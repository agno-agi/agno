"""
Translation Agent
=================

An emotion-aware translation agent that translates text, analyzes the emotional tone,
selects an appropriate voice, and generates localized audio output using Cartesia TTS.

Example:
    from translation_agent import translation_agent

    # Translate and generate audio
    translation_agent.print_response(
        "Translate 'Hello, how are you?' to French and create a voice note",
        stream=True
    )
"""

from translation_agent.agent import translation_agent

__all__ = [
    "translation_agent",
]
