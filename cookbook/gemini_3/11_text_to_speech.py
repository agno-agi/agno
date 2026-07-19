"""
Text-to-Speech - Generate Spoken Audio
========================================
Generate spoken audio from text using Gemini's TTS model.

Key concepts:
- response_modalities=["AUDIO"]: Tells Gemini to output audio instead of text
- speech_config: Configure voice name and other TTS settings
- Dedicated TTS model: Uses gemini-2.5-flash-preview-tts (not the standard model)
- response_audio: Access the audio bytes from RunOutput

Available voices: Kore, Charon, Fenrir, Aoede, Puck, and more.

Example prompts to try:
- "Say cheerfully: Have a wonderful day!"
- "Read this like a news anchor: Breaking news..."
- "Narrate this in a dramatic tone: The castle stood silent..."
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.google import Gemini
from agno.utils.audio import write_wav_audio_to_file

WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
tts_agent = Agent(
    name="TTS Agent",
    model=Gemini(
        # Dedicated TTS model, not the standard Gemini model
        id="gemini-2.5-flash-preview-tts",
        response_modalities=["AUDIO"],
        speech_config={
            "voice_config": {"prebuilt_voice_config": {"voice_name": "Kore"}}
        },
    ),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_output = tts_agent.run("Say cheerfully: Have a wonderful day!")

    if run_output.response_audio is not None:
        audio_data = run_output.response_audio.content
        output_file = str(WORKSPACE / "greeting.wav")
        write_wav_audio_to_file(output_file, audio_data)
        print(f"Audio saved to {output_file}")
    else:
        print("No audio in response")

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Voice options for speech_config:
- "Kore": Clear, professional female voice
- "Charon": Deep, authoritative male voice
- "Fenrir": Warm, conversational male voice
- "Aoede": Expressive, melodic female voice
- "Puck": Energetic, youthful voice

Changing voices:
    speech_config={
        "voice_config": {
            "prebuilt_voice_config": {"voice_name": "Charon"}
        }
    }

Use cases for music/film/gaming:
- Generate voiceover for game cutscenes
- Create narration for film trailers
- Produce podcast intros and outros
- Generate audio descriptions for accessibility
"""
