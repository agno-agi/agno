from agno.agent import Agent
from agno.models.google import Gemini
from agno.utils.audio import write_wav_audio_to_file

agent = Agent(
    model=Gemini(
        id="gemini-2.5-flash-preview-tts",
        response_modalities=["AUDIO"],
        speech_config={
            "voice_config": {"prebuilt_voice_config": {"voice_name": "Kore"}}
        },
    )
)

run_output = agent.run("Say cheerfully: Have a wonderful day!")

if run_output.response_audio is not None:
    audio_data = run_output.response_audio.content
    output_file = "tmp/cheerful_greeting.wav"
    write_wav_audio_to_file(output_file, audio_data)
