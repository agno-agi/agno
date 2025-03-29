from base64 import b64encode
from io import BytesIO
from os import getenv, path
from pathlib import Path
from typing import Iterator, Literal, Optional
from uuid import uuid4

from agno.agent import Agent
from agno.media import AudioArtifact
from agno.tools import Toolkit
from agno.utils.log import logger

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
        **kwargs,
    ):
        super().__init__(name="elevenlabs_tools", **kwargs)

        self.api_key = api_key or getenv("ELEVEN_LABS_API_KEY")
        if not self.api_key:
            logger.error("ELEVEN_LABS_API_KEY not set. Please set the ELEVEN_LABS_API_KEY environment variable.")

        self.target_directory = target_directory
        self.voice_id = voice_id
        self.model_id = model_id
        self.output_format = output_format

        if self.target_directory:
            target_path = Path(self.target_directory)
            target_path.mkdir(parents=True, exist_ok=True)

        self.eleven_labs_client = ElevenLabs(api_key=self.api_key)
        self.register(self.get_voices)
        self.register(self.generate_sound_effect)
        self.register(self.text_to_speech)

    def get_voices(self) -> str:
        """
        Use this function to get all the voices available.

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
            logger.error(f"Failed to fetch voices: {e}")
            return f"Error: {e}"

    def _process_audio(self, audio_generator: Iterator[bytes]) -> str:
        # Step 1: Write audio data to BytesIO
        audio_bytes = BytesIO()
        for chunk in audio_generator:
            audio_bytes.write(chunk)
        audio_bytes.seek(0)  # Rewind the stream

        # Step 2: Encode as Base64
        base64_audio = b64encode(audio_bytes.read()).decode("utf-8")

        # Step 3: Optionally save to disk if target_directory exists
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

            # Write from BytesIO to disk
            audio_bytes.seek(0)  # Reset the BytesIO stream again
            with open(output_path, "wb") as f:
                f.write(audio_bytes.read())

        return base64_audio

    def generate_sound_effect(self, agent: Agent, prompt: str, duration_seconds: Optional[float] = None) -> str:
        """
        Use this function to generate sound effect audio from a text prompt.

        Args:
            prompt (str): Text to generate audio from.
            duration_seconds (Optional[float]): Duration in seconds to generate audio from. Has to be between 0.5 and 22.
        Returns:
            str: Return the path to the generated audio file.
        """
        try:
            audio_generator = self.eleven_labs_client.text_to_sound_effects.convert(
                text=prompt, duration_seconds=duration_seconds
            )

            base64_audio = self._process_audio(audio_generator)

            # Attach to the agent
            agent.add_audio(
                AudioArtifact(
                    id=str(uuid4()),
                    base64_audio=base64_audio,
                    mime_type="audio/mpeg",
                )
            )

            return "Audio generated successfully"

        except Exception as e:
            logger.error(f"Failed to generate audio: {e}")
            return f"Error: {e}"

    def text_to_speech(self, agent: Agent, prompt: str) -> str:
        """
        Use this function to convert text to speech audio.

        Args:
            prompt (str): Text to generate audio from.
        Returns:
            str: Return the path to the generated audio file.
        """
        try:
            audio_generator = self.eleven_labs_client.text_to_speech.convert(
                text=prompt,
                voice_id=self.voice_id,
                model_id=self.model_id,
                output_format=self.output_format,
            )

            base64_audio = self._process_audio(audio_generator)

            # Attach to the agent
            agent.add_audio(
                AudioArtifact(
                    id=str(uuid4()),
                    base64_audio=base64_audio,
                    mime_type="audio/mpeg",
                )
            )

            return "Audio generated successfully"

        except Exception as e:
            logger.error(f"Failed to generate audio: {e}")
            return f"Error: {e}"
