from io import BytesIO
from os import getenv, path
from pathlib import Path
from typing import Any, Iterator, List, Literal, Optional, Union
from uuid import uuid4

from agno.agent import Agent
from agno.media import Audio
from agno.team.team import Team
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_error, log_info

try:
    from elevenlabs import ElevenLabs  # type: ignore
except ImportError:
    raise ImportError("`elevenlabs` not installed. Please install using `pip install elevenlabs`")

ElevenLabsAudioOutputFormat = Literal[
    "mp3_22050_32",  # mp3 with 22.05kHz sample rate at 32kbps
    "mp3_44100_32",  # mp3 with 44.1kHz sample rate at 32kbps
    "mp3_44100_64",  # mp3 with 44.1kHz sample rate at 64kbps
    "mp3_44100_96",  # mp3 with 44.1kHz sample rate at 96kbps
    "mp3_44100_128",  # default, mp3 with 44.1kHz sample rate at 128kbps
    "mp3_44100_192",  # mp3 with 44.1kHz sample rate at 192kbps (Creator tier+)
    "pcm_16000",  # PCM format (S16LE) with 16kHz sample rate
    "pcm_22050",  # PCM format (S16LE) with 22.05kHz sample rate
    "pcm_24000",  # PCM format (S16LE) with 24kHz sample rate
    "pcm_44100",  # PCM format (S16LE) with 44.1kHz sample rate (Pro tier+)
    "ulaw_8000",  # μ-law format with 8kHz sample rate (for Twilio)
]


class ElevenLabsTools(Toolkit):
    def __init__(
        self,
        voice_id: str = "JBFqnCBsd6RMkjVDRZzb",
        api_key: Optional[str] = None,
        target_directory: Optional[str] = None,
        model_id: str = "eleven_multilingual_v2",
        output_format: ElevenLabsAudioOutputFormat = "mp3_44100_64",
        enable_get_voices: bool = True,
        enable_generate_sound_effect: bool = True,
        enable_text_to_speech: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("ELEVEN_LABS_API_KEY")
        if not self.api_key:
            log_error("ELEVEN_LABS_API_KEY not set. Please set the ELEVEN_LABS_API_KEY environment variable.")

        self.target_directory = target_directory
        self.voice_id = voice_id
        self.model_id = model_id
        self.output_format = output_format

        if self.target_directory:
            target_path = Path(self.target_directory)
            target_path.mkdir(parents=True, exist_ok=True)

        self.eleven_labs_client = ElevenLabs(api_key=self.api_key)

        tools: List[Any] = []
        if all or enable_get_voices:
            tools.append(self.get_voices)
        if all or enable_generate_sound_effect:
            tools.append(self.generate_sound_effect)
        if all or enable_text_to_speech:
            tools.append(self.text_to_speech)

        super().__init__(name="elevenlabs_tools", tools=tools, **kwargs)

    def get_voices(self) -> str:
        """
        Get all the voices available.

        Returns:
            result (list): A list of voices that have an ID, name and description.
        """
        try:
            voices = self.eleven_labs_client.voices.get_all()

            response = []
            for voice in voices.voices:
                response.append(
                    {
                        "id": voice.voice_id,
                        "name": voice.name,
                        "description": voice.description,
                    }
                )

            return str(response)

        except Exception as e:
            log_error(f"Failed to fetch voices: {e}")
            return f"Error: {e}"

    def _process_audio(self, audio_generator: Iterator[bytes]) -> bytes:
        audio_bytes = BytesIO()
        for chunk in audio_generator:
            audio_bytes.write(chunk)

        # Read bytes
        audio_bytes.seek(0)
        audio_data = audio_bytes.read()

        # Save to disk if target_directory exists
        if self.target_directory:
            # Determine file extension based on output format
            if self.output_format.startswith("mp3"):
                extension = "mp3"
            elif self.output_format.startswith("pcm"):
                extension = "wav"
            elif self.output_format.startswith("ulaw"):
                extension = "ulaw"
            else:
                extension = "mp3"

            output_filename = f"{uuid4()}.{extension}"
            output_path = path.join(self.target_directory, output_filename)

            with open(output_path, "wb") as f:
                f.write(audio_data)

            log_info(f"Audio saved to: {output_path}")

        return audio_data

    def generate_sound_effect(self, prompt: str, duration_seconds: Optional[float] = None) -> ToolResult:
        """
        Generate a sound effect from a text description.

        Args:
            prompt (str): Description of the sound effect
            duration_seconds (Optional[float]): Duration in seconds to generate audio from. Has to be between 0.5 and 22.
        Returns:
            ToolResult: A ToolResult containing the generated audio or error message.
        """
        try:
            audio_generator = self.eleven_labs_client.text_to_sound_effects.convert(
                text=prompt, duration_seconds=duration_seconds
            )

            audio_data = self._process_audio(audio_generator)

            # Create AudioArtifact
            audio_artifact = Audio(
                id=str(uuid4()),
                content=audio_data,
                mime_type="audio/mpeg",
            )

            return ToolResult(
                content="Sound effect generated successfully",
                audios=[audio_artifact],
            )

        except Exception as e:
            log_error(f"Failed to generate sound effect: {e}")
            return ToolResult(content=f"Error: {e}")

    def text_to_speech(self, agent: Union[Agent, Team], prompt: str) -> ToolResult:
        """
        Convert text to speech.

        Args:
            prompt (str): Text to generate audio from.
        Returns:
            ToolResult: A ToolResult containing the generated audio or error message.
        """
        try:
            audio_generator = self.eleven_labs_client.text_to_speech.convert(
                text=prompt,
                voice_id=self.voice_id,
                model_id=self.model_id,
                output_format=self.output_format,
            )

            audio_data = self._process_audio(audio_generator)

            # Create AudioArtifact
            audio_artifact = Audio(
                id=str(uuid4()),
                content=audio_data,
                mime_type="audio/mpeg",
            )

            return ToolResult(
                content="Audio generated successfully",
                audios=[audio_artifact],
            )

        except Exception as e:
            log_error(f"Failed to generate audio: {e}")
            return ToolResult(content=f"Error: {e}")
