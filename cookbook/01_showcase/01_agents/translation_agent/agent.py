"""
Translation Agent
=================

An emotion-aware translation agent that translates text, analyzes the emotional tone,
selects an appropriate voice, and generates localized audio output using Cartesia TTS.

Example prompts:
- "Translate 'Hello, how are you?' to French and create a voice note"
- "Convert 'I'm so excited about this!' to Spanish with audio"
- "Translate this sad message to German: 'I'm sorry for your loss'"

Usage:
    from agent import translation_agent

    # Interactive translation
    response = translation_agent.run(
        "Translate 'Hello!' to French and create audio"
    )

    # Access audio
    if response.audio:
        # Audio bytes available in response.audio[0].content
        pass
"""

import base64
from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.cartesia import CartesiaTools
from agno.utils.media import save_base64_data

# ============================================================================
# Agent Instructions
# ============================================================================
AGENT_INSTRUCTIONS = dedent("""\
    Follow these steps SEQUENTIALLY to translate text and generate a localized voice note:

    1. **Identify Input**
       - Extract the text to translate from the user request
       - Identify the target language

    2. **Translate**
       - Translate the text accurately to the target language
       - Preserve the meaning and tone
       - Keep the translated text for audio generation

    3. **Analyze Emotion**
       - Analyze the emotion conveyed by the translated text
       - Categories: neutral, happy, sad, angry, excited, calm, professional
       - This will guide voice selection

    4. **Get Language Code**
       - Determine the 2-letter language code for the target language
       - Examples: 'fr' (French), 'es' (Spanish), 'de' (German), 'ja' (Japanese)

    5. **List Available Voices**
       - Call the 'list_voices' tool to get available Cartesia voices
       - Wait for the result

    6. **Select Base Voice**
       - From the list, select a voice ID that:
         a) Matches or is close to the target language
         b) Reflects the analyzed emotion
       - Note: If exact language match unavailable, select a suitable base voice

    7. **Localize Voice**
       - Call 'localize_voice' to create a language-specific voice:
         - voice_id: The selected base voice ID
         - name: Descriptive name (e.g., "French Happy Female")
         - description: Language and emotion description
         - language: Target language code from step 4
         - original_speaker_gender: Inferred or user-specified gender
       - Wait for the result and extract the new voice ID

    8. **Generate Audio**
       - Call 'text_to_speech' with:
         - transcript: The translated text from step 2
         - voice_id: The localized voice ID from step 7
       - Wait for audio generation

    9. **Return Results**
       - Provide the user with:
         - Original text
         - Translated text
         - Detected emotion
         - Language code
         - Confirmation that audio was generated

    ## Emotion-Voice Guidelines

    | Emotion | Voice Characteristics |
    |---------|----------------------|
    | Neutral | Clear, professional, moderate pace |
    | Happy | Upbeat, energetic, slightly faster |
    | Sad | Slower, softer, lower energy |
    | Angry | Stronger, more intense |
    | Excited | High energy, dynamic, faster |
    | Calm | Soothing, steady, relaxed |
    | Professional | Formal, clear, authoritative |

    ## Language Codes Reference

    - French: fr
    - Spanish: es
    - German: de
    - Italian: it
    - Portuguese: pt
    - Japanese: ja
    - Chinese: zh
    - Korean: ko
    - Russian: ru
    - Arabic: ar
""")


# ============================================================================
# Create the Agent
# ============================================================================
translation_agent = Agent(
    name="Translation Agent",
    description=(
        "Translates text, analyzes emotion, selects a suitable voice, "
        "creates a localized voice, and generates a voice note using Cartesia TTS."
    ),
    instructions=AGENT_INSTRUCTIONS,
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[CartesiaTools()],
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    enable_agentic_memory=True,
    markdown=True,
    db=SqliteDb(db_file="tmp/data.db"),
)


# ============================================================================
# Helper Functions
# ============================================================================
def translate_and_speak(
    text: str,
    target_language: str,
    output_path: str | None = None,
) -> dict:
    """Translate text and generate audio.

    Args:
        text: Text to translate.
        target_language: Target language name (e.g., "French", "Spanish").
        output_path: Optional path to save the audio file.

    Returns:
        Dictionary with translation results and audio path.
    """
    prompt = f"Translate '{text}' to {target_language} and create a voice note"

    response = translation_agent.run(prompt)

    result = {
        "original_text": text,
        "target_language": target_language,
        "response": str(response.content),
        "audio_path": None,
    }

    if response.audio:
        audio_content = response.audio[0].content
        base64_audio = base64.b64encode(audio_content).decode("utf-8")

        if output_path is None:
            output_dir = Path("tmp/translations")
            output_dir.mkdir(parents=True, exist_ok=True)
            lang_code = target_language.lower()[:2]
            output_path = str(output_dir / f"translation_{lang_code}.mp3")

        save_base64_data(base64_data=base64_audio, output_path=output_path)
        result["audio_path"] = output_path

    return result


# ============================================================================
# Exports
# ============================================================================
__all__ = [
    "translation_agent",
    "translate_and_speak",
]

if __name__ == "__main__":
    translation_agent.cli_app(stream=True)
