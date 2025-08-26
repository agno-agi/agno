from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIChat
from agno.utils.audio import write_audio_to_file


# Provide the agent with the audio file and audio configuration and get result as text + audio
agent = Agent(
    model=OpenAIChat(
        id="gpt-4o-audio-preview",
        modalities=["text", "audio"],
        audio={"voice": "sage", "format": "wav"},
    ),
    add_history_to_context=True,
    markdown=True,
)
run_output: RunOutput = agent.run("Tell me a 5 second scary story")

# Save the response audio to a file
if run_output.response_audio:
    write_audio_to_file(
        audio=run_output.response_audio.content, filename="tmp/scary_story.wav"
    )

run_output: RunOutput = agent.run("What would be in a sequal of this story?")

# Save the response audio to a file
if run_output.response_audio:
    write_audio_to_file(
        audio=run_output.response_audio.content,
        filename="tmp/scary_story_sequal.wav",
    )
