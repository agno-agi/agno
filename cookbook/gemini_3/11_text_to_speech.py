"""
11. Text-to-Speech
==================
Gemini can generate spoken audio from text using the TTS model.
Set response_modalities=["AUDIO"] and configure a voice.

Run:
    python cookbook/gemini_3/11_text_to_speech.py

Output: workspace/greeting.wav
"""

from pathlib import Path

from agno.agent import Agent
from agno.models.google import Gemini
from agno.utils.audio import write_wav_audio_to_file

# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
tts_agent = Agent(
    name="TTS Agent",
    model=Gemini(
        id="gemini-2.5-flash-preview-tts",
        response_modalities=["AUDIO"],
        speech_config={
            "voice_config": {
                "prebuilt_voice_config": {"voice_name": "Kore"}
            }
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
