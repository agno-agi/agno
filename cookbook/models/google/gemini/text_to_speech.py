from agno.agent import Agent
from agno.models.google import Gemini
from agno.utils.audio import save_wave_file

agent = Agent(
    model=Gemini(
        id="gemini-2.5-flash-preview-tts",
        response_modalities=["AUDIO"],
        speech_config={
            "voice_config": {"prebuilt_voice_config": {"voice_name": "Kore"}}
        },
    )
)

agent.run("Say cheerfully: Have a wonderful day!")

if agent.run_response.response_audio is not None:
    audio_data = agent.run_response.response_audio.binary_data
    output_file = "tmp/generated_speech.wav"
    save_wave_file(output_file, audio_data)