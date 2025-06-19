from pathlib import Path

import requests
from agno.agent import Agent, RunResponse  # noqa
from agno.models.openai import OpenAIChat
from agno.utils.audio import write_audio_to_file

# Fetch the audio file and convert it to a base64 encoded string
url = "https://openaiassets.blob.core.windows.net/$web/API/docs/audio/alloy.wav"
response = requests.get(url)
response.raise_for_status()
wav_data = response.content

# Provide the agent with the audio file and audio configuration and get result as text + audio
agent = Agent(
    model=OpenAIChat(
        id="gpt-4o-audio-preview",
        modalities=["text", "audio"],
        audio={"voice": "alloy", "format": "wav"},
    ),
    # Set add_history_to_messages=true to add the previous chat history to the messages sent to the Model.
    add_history_to_messages=True,
    # Number of historical responses to add to the messages.
    num_history_responses=3,
)
agent.print_response(
    "What is in this audio?", audio={"data": wav_data, "format": "wav"}
)

filename = Path(__file__).parent.joinpath("tmp/conversation_response_1.wav")
filename.unlink(missing_ok=True)
filename.parent.mkdir(parents=True, exist_ok=True)

# Save the response audio to a file
if agent.run_response.response_audio is not None:
    write_audio_to_file(
        audio=agent.run_response.response_audio.base64_audio, filename=str(filename)
    )


agent.print_response("Tell me something more about the audio")

filename = Path(__file__).parent.joinpath("tmp/conversation_response_2.wav")
filename.unlink(missing_ok=True)

# Save the response audio to a file
if agent.run_response.response_audio is not None:
    write_audio_to_file(
        audio=agent.run_response.response_audio.base64_audio, filename=str(filename)
    )


agent.print_response("Now tell me a 5 second story")

filename = Path(__file__).parent.joinpath("tmp/conversation_response_3.wav")
filename.unlink(missing_ok=True)

# Save the response audio to a file
if agent.run_response.response_audio is not None:
    write_audio_to_file(
        audio=agent.run_response.response_audio.base64_audio, filename=str(filename)
    )
