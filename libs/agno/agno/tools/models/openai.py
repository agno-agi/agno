import json
from os import getenv
from typing import Callable, List, Literal, Optional, Union
from uuid import uuid4

from agno.agent import Agent
from agno.media import Audio, Image
from agno.team.team import Team
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_debug, log_error, log_warning

try:
    from openai import OpenAI as OpenAIClient
except (ModuleNotFoundError, ImportError):
    raise ImportError("`openai` not installed. Please install using `pip install openai`")

# Define only types specifically needed by OpenAITools class
OpenAIVoice = Literal["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
OpenAITTSModel = Literal["tts-1", "tts-1-hd"]
OpenAITTSFormat = Literal["mp3", "opus", "aac", "flac", "wav", "pcm"]
OpenAIImageSize = Literal["auto", "256x256", "512x512", "1024x1024", "1536x1024", "1024x1536", "1792x1024", "1024x1792"]


class OpenAITools(Toolkit):
    """Tools for interacting with OpenAI API.

    Args:
        api_key: OpenAI API key. Retrieved from OPENAI_API_KEY env variable if not provided.
        transcribe_audio: Whether to register the transcribe_audio tool.
        generate_image: Whether to register the generate_image tool.
        generate_speech: Whether to register the generate_speech tool.
        all: Whether to register all tools.
        transcription_model: Model to use for transcription.
        text_to_speech_voice: Voice to use for TTS.
        text_to_speech_model: Model to use for TTS.
        text_to_speech_format: Audio format for TTS.
        image_model: Model to use for image generation.
        image_quality: Quality setting for image generation.
        image_size: Size setting for image generation.
        image_style: Style setting for image generation.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        transcribe_audio: bool = True,
        generate_image: bool = True,
        generate_speech: bool = True,
        all: bool = False,
        transcription_model: str = "whisper-1",
        text_to_speech_voice: OpenAIVoice = "alloy",
        text_to_speech_model: OpenAITTSModel = "tts-1",
        text_to_speech_format: OpenAITTSFormat = "mp3",
        image_model: Optional[str] = "gpt-image-2",
        image_quality: Optional[str] = None,
        image_size: Optional[OpenAIImageSize] = None,
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

        tools: List[Callable] = []
        if all or transcribe_audio:
            tools.append(self.transcribe_audio)
        if all or generate_image:
            tools.append(self.generate_image)
        if all or generate_speech:
            tools.append(self.generate_speech)

        super().__init__(name="openai_tools", tools=tools, **kwargs)

    def transcribe_audio(self, audio_path: str) -> str:
        """Transcribe audio file using OpenAI's Whisper API.

        Args:
            audio_path: Path to the audio file.

        Returns:
            JSON with transcript text or error message.
        """
        log_debug(f"Transcribing audio from {audio_path}")
        try:
            with open(audio_path, "rb") as audio_file:
                transcript = OpenAIClient(api_key=self.api_key).audio.transcriptions.create(
                    model=self.transcription_model,
                    file=audio_file,
                    response_format="text",
                )
        except Exception as e:
            log_error(f"Failed to transcribe audio: {str(e)}")
            return json.dumps({"error": f"Failed to transcribe audio: {str(e)}"})

        log_debug(f"Transcript: {transcript}")
        return json.dumps({"transcript": transcript})

    def generate_image(
        self,
        prompt: str,
    ) -> ToolResult:
        """Generate images based on a text prompt.

        Args:
            prompt: The text prompt to generate the image from.

        Returns:
            ToolResult containing the generated image.
        """
        try:
            import base64

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
                return ToolResult(content="Failed to generate image: No data received from API.")

            if hasattr(data, "b64_json") and data.b64_json:
                image_base64 = data.b64_json
                media_id = str(uuid4())

                # Decode base64 to bytes for proper storage
                image_bytes = base64.b64decode(image_base64)

                # Create ImageArtifact and return in ToolResult
                image_artifact = Image(
                    id=media_id,
                    content=image_bytes,  # ← Store as bytes, not encoded string
                    mime_type="image/png",
                    original_prompt=prompt,
                )

                return ToolResult(
                    content="Image generated successfully.",
                    images=[image_artifact],
                )

            return ToolResult(content="Failed to generate image: No content received from API.")
        except Exception as e:
            log_error(f"Failed to generate image using {self.image_model}: {str(e)}")
            return ToolResult(content=f"Failed to generate image: {e}")

    def generate_speech(
        self,
        agent: Union[Agent, Team],
        text_input: str,
    ) -> ToolResult:
        """Generate speech from text using OpenAI's Text-to-Speech API.

        Args:
            text_input: The text to synthesize into speech.

        Returns:
            ToolResult containing the generated audio.
        """
        try:
            response = OpenAIClient(api_key=self.api_key).audio.speech.create(
                model=self.tts_model,
                voice=self.tts_voice,
                input=text_input,
                response_format=self.tts_format,
            )

            # Get raw audio data for artifact creation before potentially saving
            audio_data: bytes = response.content

            # Create AudioArtifact and return in ToolResult
            media_id = str(uuid4())
            audio_artifact = Audio(
                id=media_id,
                content=audio_data,
                mime_type=f"audio/{self.tts_format}",
            )

            return ToolResult(
                content=f"Speech generated successfully with ID: {media_id}",
                audios=[audio_artifact],
            )
        except Exception as e:
            return ToolResult(content=f"Failed to generate speech: {str(e)}")
