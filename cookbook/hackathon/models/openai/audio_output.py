from agno.agent import Agent, RunResponse
from agno.models.openai import OpenAIChat
from agno.utils.audio import write_audio_to_file

agent = Agent(
    model=OpenAIChat(
        id="gpt-4o-audio-preview",
        modalities=["text", "audio"],
        audio={"voice": "alloy", "format": "wav"},
    ),
    markdown=True,
)
response: RunResponse = agent.run("Tell me a 5 second scary story")

# Save the response audio to a file
if response.response_audio is not None:
    write_audio_to_file(
        audio=agent.run_response.response_audio.content, filename="tmp/scary_story.wav"
    )
