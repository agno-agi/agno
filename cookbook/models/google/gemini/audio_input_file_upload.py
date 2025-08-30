from pathlib import Path

from agno.agent import Agent
from agno.media import Audio
from agno.models.google import Gemini
from google.genai.types import UploadFileConfig

model = Gemini(id="gemini-2.0-flash-exp")
agent = Agent(
    model=model,
    markdown=True,
)

# Please download a sample audio file to test this Agent and upload using:
audio_path = Path(__file__).parent.joinpath("sample.mp3")
audio_file = None

remote_file_name = f"files/{audio_path.stem.lower()}"
try:
    audio_file = model.get_client().files.get(name=remote_file_name)
except Exception as e:
    print(f"Error getting file {audio_path.stem}: {e}")
    pass

if not audio_file:
    try:
        audio_file = model.get_client().files.upload(
            file=audio_path,
            config=UploadFileConfig(name=audio_path.stem, display_name=audio_path.stem),
        )
        print(f"Uploaded audio: {audio_file}")
    except Exception as e:
        print(f"Error uploading audio: {e}")

agent.print_response(
    "Tell me about this audio",
    audio=[Audio(content=audio_file)],
    stream=True,
)
