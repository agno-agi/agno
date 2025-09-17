from pathlib import Path

from agno.agent import Agent, RunOutput
from agno.media import Image
from agno.models.openai import OpenAIChat
from agno.utils.audio import write_audio_to_file
from rich import print
from rich.text import Text

cwd = Path(__file__).parent.resolve()

image_agent = Agent(model=OpenAIChat(id="gpt-4o"))

image_path = Path(__file__).parent.joinpath("sample.jpg")
image_story: RunOutput = image_agent.run(
    "Write a 3 sentence fiction story about the image",
    images=[Image(filepath=image_path)],
)
formatted_text = Text.from_markup(
    f":sparkles: [bold magenta]Story:[/bold magenta] {image_story.content} :sparkles:"
)
print(formatted_text)

audio_agent = Agent(
    model=OpenAIChat(
        id="gpt-4o-audio-preview",
        modalities=["text", "audio"],
        audio={"voice": "sage", "format": "wav"},
    ),
)

audio_story: RunOutput = audio_agent.run(
    f"Narrate the story with flair: {image_story.content}"
)
if audio_story.response_audio is not None:
    write_audio_to_file(
        audio=audio_story.response_audio.content, filename="tmp/sample_story.wav"
    )
