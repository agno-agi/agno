from os import getenv
from typing import Any, List, Literal, Optional
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
        transcription_model: str = "whisper-1",
        text_to_speech_voice: OpenAIVoice = "alloy",
        text_to_speech_model: OpenAITTSModel = "tts-1",
        text_to_speech_format: OpenAITTSFormat = "mp3",
        image_model: Optional[str] = "dall-e-3",
        image_quality: Optional[str] = None,
        image_size: Optional[Literal["256x256", "512x512", "1024x1024", "1792x1024", "1024x1792"]] = None,
        image_style: Optional[Literal["vivid", "natural"]] = None,
        **kwargs,
    ):
        self.api_key = api_key or getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set. Please set the OPENAI_API_KEY environment variable.")

        self.transcription_model = transcription_model
        # Store TTS defaults
        self.tts_voice = text_to_speech_voice
        self.tts_model = text_to_speech_model
        self.tts_format = text_to_speech_format
        self.image_model = image_model
        self.image_quality = image_quality
        self.image_style = image_style
        self.image_size = image_size

        tools: List[Any] = []
        if enable_transcription:
            tools.append(self.transcribe_audio)
        if enable_image_generation:
            tools.append(self.generate_image)
        if enable_speech_generation:
            tools.append(self.generate_speech)

        super().__init__(name="openai_tools", tools=tools, **kwargs)

    def transcribe_audio(self, audio_path: str) -> str:
        """Transcribe audio file using OpenAI's Whisper API
        Args:
            audio_path: Path to the audio file
        """
        log_debug(f"Transcribing audio from {audio_path}")
        try:
            audio_file = open(audio_path, "rb")

            transcript = OpenAIClient(api_key=self.api_key).audio.transcriptions.create(
                model=self.transcription_model,
                file=audio_file,
                response_format="text",
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
        """
        try:
            extra_params = {
                "size": self.image_size,
                "quality": self.image_quality,
                "style": self.image_style,
            }
            extra_params = {k: v for k, v in extra_params.items() if v is not None}

            # gpt-image-1 by default outputs a base64 encoded image but other models do not
            # so we add a response_format parameter to have consistent output.
            if self.image_model and self.image_model.startswith("gpt-image"):
                response = OpenAIClient(api_key=self.api_key).images.generate(
                    model=self.image_model,
                    prompt=prompt,
                    **extra_params,  # type: ignore
                )
            else:
                response = OpenAIClient(api_key=self.api_key).images.generate(
                    model=self.image_model,
                    prompt=prompt,
                    response_format="b64_json",
                    **extra_params,  # type: ignore
                )
            data = None
            if hasattr(response, "data") and response.data:
                data = response.data[0]
            if data is None:
                log_warning("OpenAI API did not return any data.")
                return "Failed to generate image: No data received from API."
            if hasattr(data, "b64_json") and data.b64_json:
                image_base64 = data.b64_json
                media_id = str(uuid4())
                # Store base64-encoded content as bytes for later saving
                agent.add_image(
                    ImageArtifact(
                        id=media_id,
                        content=image_base64.encode("utf-8"),
                        mime_type="image/png",
                    )
                )
                return "Image generated successfully."
            return "Failed to generate image: No content received from API."
        except Exception as e:
            log_error(f"Failed to generate image using {self.image_model}: {e}")
            return f"Failed to generate image: {e}"

    def generate_speech(
        self,
        agent: Agent,
        text_input: str,
    ) -> str:
        """Generate speech from text using OpenAI's Text-to-Speech API.
        Args:
            text_input (str): The text to synthesize into speech.
        """
        try:
            import base64

            response = OpenAIClient(api_key=self.api_key).audio.speech.create(
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
                )
            )
            return f"Speech generated successfully with ID: {media_id}"
        except Exception as e:
            return f"Failed to generate speech: {str(e)}"
