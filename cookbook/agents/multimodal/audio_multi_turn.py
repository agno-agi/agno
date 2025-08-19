from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.utils.audio import write_audio_to_file

agent = Agent(
    model=OpenAIChat(
        id="gpt-4o-audio-preview",
        modalities=["text", "audio"],
        audio={"voice": "sage", "format": "wav"},
    ),
    add_history_to_context=True,
)

run_response = agent.run("Is a golden retriever a good family dog?")
if run_response.response_audio is not None:
    write_audio_to_file(
        audio=run_response.response_audio.content, filename="tmp/answer_1.wav"
    )

run_response = agent.run("Why do you say they are loyal?")
if run_response.response_audio is not None:
    write_audio_to_file(
        audio=run_response.response_audio.content, filename="tmp/answer_2.wav"
    )
