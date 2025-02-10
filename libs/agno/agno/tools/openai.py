from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from openai import OpenAI as OpenAIClient
except (ModuleNotFoundError, ImportError):
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


client = OpenAIClient()


class OpenAITools(Toolkit):
    """Tools for interacting with OpenAIChat API"""

    def __init__(self):
        super().__init__(name="openai_tools")

        self.register(self.transcribe_audio)

    def transcribe_audio(self, audio_path: str) -> str:
        """Transcribe audio file using OpenAI's Whisper API
        Args:
            audio_path: Path to the audio file
        Returns:
            str: Transcribed text
        """
        logger.info(f"Transcribing audio from {audio_path}")
        try:
            with open(audio_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1", file=audio_file, response_format="srt"
                )
                logger.info(f"Transcript: {transcript}")
            return transcript
        except Exception as e:
            logger.error(f"Failed to transcribe audio: {str(e)}")
            return f"Failed to transcribe audio: {str(e)}"
