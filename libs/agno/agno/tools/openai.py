from os import getenv
from typing import Literal, Optional
from uuid import uuid4

from agno.agent import Agent
from agno.media import AudioArtifact, ImageArtifact
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_warning

try:
    from openai import OpenAI as OpenAIClient
except (ModuleNotFoundError, ImportError):
    raise ImportError("`openai` not installed. Please install using `pip install openai`")

# Define only types specifically needed by OpenAITools class
OpenAIVoice = Literal["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
OpenAITTSModel = Literal["tts-1", "tts-1-hd"]
OpenAITTSFormat = Literal["mp3", "opus", "aac", "flac", "wav", "pcm"]


class OpenAITools(Toolkit):
    """Tools for interacting with OpenAIChat API"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_transcription: bool = True,
        enable_image_generation: bool = True,
        enable_speech_generation: bool = True,
        text_to_speech_voice: OpenAIVoice = "alloy",
        text_to_speech_model: OpenAITTSModel = "tts-1",
        text_to_speech_format: OpenAITTSFormat = "mp3",
        image_model: Optional[str] = "dall-e-3",
        **kwargs,
    ):
        super().__init__(name="openai_tools", **kwargs)

        self.api_key = api_key or getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set. Please set the OPENAI_API_KEY environment variable.")

        # Store TTS defaults
        self.tts_voice = text_to_speech_voice
        self.tts_model = text_to_speech_model
        self.tts_format = text_to_speech_format
        self.image_model = image_model

        if enable_transcription:
            self.register(self.transcribe_audio)
        if enable_image_generation:
            self.register(self.generate_image)
        if enable_speech_generation:
            self.register(self.generate_speech)

    def transcribe_audio(self, audio_path: str) -> str:
        """Transcribe audio file using OpenAI's Whisper API
        Args:
            audio_path: Path to the audio file
        Returns:
            str: Transcribed text
        """
        log_debug(f"Transcribing audio from {audio_path}")
        try:
            with open(audio_path, "rb") as audio_file:
                transcript = OpenAIClient().audio.transcriptions.create(
                    model="whisper-1", file=audio_file, response_format="srt"
                )
        except Exception as e:  # type: ignore[return]
            log_error(f"Failed to transcribe audio: {str(e)}")
            return f"Failed to transcribe audio: {str(e)}"

        log_debug(f"Transcript: {transcript}")
        return transcript  # type: ignore[return-value]

    def generate_image(
        self,
        agent: Agent,
        prompt: str,
    ) -> str:
        """Generate images based on a text prompt.
        Args:
            prompt (str): The text prompt to generate the image from.
        Returns:
            str: Return the result of the model.
        """
        try:
            response = OpenAIClient().images.generate(
                model=self.image_model,
                prompt=prompt,
                response_format="url",
            )

            if response.data and response.data[0].url:
                image_url = response.data[0].url
                media_id = str(uuid4())
                agent.add_image(
                    ImageArtifact(
                        id=media_id,
                        url=image_url,
                        prompt=prompt,
                        model=self.image_model,
                    )
                )
                return f"Image generated successfully: {image_url}"
            else:
                log_warning("OpenAI API did not return an image URL.")
                return "Failed to generate image: No URL received from API."

        except Exception as e:
            log_error(f"Failed to generate image using {self.image_model}: {str(e)}")
            return f"Failed to generate image: {str(e)}"

    def generate_speech(
        self,
        agent: Agent,
        text_input: str,
    ) -> str:
        """Generate speech from text using OpenAI's Text-to-Speech API.
        Args:
            text_input (str): The text to synthesize into speech.
        Returns:
            str: Return the result of the model.
        """
        try:
            import base64

            response = OpenAIClient().audio.speech.create(
                model=self.tts_model,
                voice=self.tts_voice,
                input=text_input,
                response_format=self.tts_format,
            )

            # Get raw audio data for artifact creation before potentially saving
            audio_data: bytes = response.content

            # Base64 encode the audio data
            base64_encoded_audio = base64.b64encode(audio_data).decode("utf-8")

            # Create and add AudioArtifact using base64_audio field
            media_id = str(uuid4())
            agent.add_audio(
                AudioArtifact(
                    id=media_id,
                    base64_audio=base64_encoded_audio,
                    format=self.tts_format,
                    model=self.tts_model,
                    voice=self.tts_voice,
                )
            )
            return f"Speech generated successfully with ID: {media_id}"
        except Exception as e:
            return f"Failed to generate speech: {str(e)}"
