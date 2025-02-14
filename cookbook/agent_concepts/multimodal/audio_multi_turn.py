from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.utils.audio import write_audio_to_file

agent = Agent(
    model=OpenAIChat(
        id="gpt-4o-audio-preview",
        modalities=["text", "audio"],
        audio={"voice": "sage", "format": "wav"},
    ),
    debug_mode=True,
    add_history_to_messages=True,
)

agent.run("Is a golden retriever a good family dog?")
if agent.run_response.response_audio is not None:
    write_audio_to_file(
        audio=agent.run_response.response_audio.content, filename="tmp/answer_1.wav"
    )

agent.run("Why do you say they are loyal?")
if agent.run_response.response_audio is not None:
    write_audio_to_file(
        audio=agent.run_response.response_audio.content, filename="tmp/answer_2.wav"
    )
