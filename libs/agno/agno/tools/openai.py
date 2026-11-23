from os import getenv
from typing import Any, Dict, List, Literal, Optional, Union
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
_GPT_IMAGE_QUALITIES = ["auto", "low", "medium", "high"]
_FIXED_GPT_IMAGE_SIZES = ["auto", "1024x1024", "1536x1024", "1024x1536"]
# Sizes and qualities each known image model accepts. Models not listed here are passed through unchecked.
# gpt-image-2 takes custom resolutions, so its sizes are left for the API to validate.
IMAGE_MODEL_OPTIONS: Dict[str, Dict[str, List[str]]] = {
    "gpt-image-2": {"qualities": _GPT_IMAGE_QUALITIES},
    "gpt-image-1.5": {"sizes": _FIXED_GPT_IMAGE_SIZES, "qualities": _GPT_IMAGE_QUALITIES},
    "gpt-image-1-mini": {"sizes": _FIXED_GPT_IMAGE_SIZES, "qualities": _GPT_IMAGE_QUALITIES},
}


STYLE_DEPRECATION = (
    "The image style option is deprecated and ignored: OpenAI image models reject the style parameter. "
    "It will be removed in a future release."
)


def validate_image_options(model: Optional[str], n: int, size: Optional[str], quality: Optional[str]) -> None:
    """Raise ValueError for an image count, size or quality the model does not accept."""
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        raise ValueError("Invalid number of images. Please provide a positive integer.")
    options = IMAGE_MODEL_OPTIONS.get(model or "")
    if options is None:
        return
    sizes = options.get("sizes")
    if size is not None and sizes is not None and size not in sizes:
        raise ValueError(f"Invalid size for {model}. Please choose from {', '.join(sizes)}.")
    if quality is not None and quality not in options["qualities"]:
        raise ValueError(f"Invalid quality for {model}. Please choose from {', '.join(options['qualities'])}.")


class OpenAITools(Toolkit):
    """Tools for interacting with OpenAI API.

    Args:
        api_key (str, optional): OpenAI API key. Retrieved from OPENAI_API_KEY env variable if not provided.
        enable_transcription (bool): Enable audio transcription functionality. Default is True.
        enable_image_generation (bool): Enable image generation functionality. Default is True.
        enable_speech_generation (bool): Enable speech generation functionality. Default is True.
        all (bool): Enable all tools. Overrides individual flags when True. Default is False.
        transcription_model (str): Model to use for transcription. Default is "whisper-1".
        text_to_speech_voice (OpenAIVoice): Voice to use for TTS. Default is "alloy".
        text_to_speech_model (OpenAITTSModel): Model to use for TTS. Default is "tts-1".
        text_to_speech_format (OpenAITTSFormat): Audio format for TTS. Default is "mp3".
        image_model (str, optional): Model to use for image generation. Default is "gpt-image-2".
        image_quality (str, optional): Quality setting for image generation.
        image_size (str, optional): Size setting for image generation, e.g. "1024x1024" or "auto". gpt-image-2 also accepts custom resolutions.
        image_style (str, optional): Deprecated and ignored; image models reject the style parameter.
        image_n (int): Number of images to generate per call. Default is 1.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_transcription: bool = True,
        enable_image_generation: bool = True,
        enable_speech_generation: bool = True,
        all: bool = False,
        transcription_model: str = "whisper-1",
        text_to_speech_voice: OpenAIVoice = "alloy",
        text_to_speech_model: OpenAITTSModel = "tts-1",
        text_to_speech_format: OpenAITTSFormat = "mp3",
        image_model: Optional[str] = "gpt-image-2",
        image_quality: Optional[str] = None,
        image_size: Optional[str] = None,
        image_style: Optional[Literal["vivid", "natural"]] = None,
        image_n: int = 1,
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
        self.image_n = image_n
        if all or enable_image_generation:
            validate_image_options(image_model, image_n, image_size, image_quality)
            if image_style is not None:
                log_warning(STYLE_DEPRECATION)

        tools: List[Any] = []
        if all or enable_transcription:
            tools.append(self.transcribe_audio)
        if all or enable_image_generation:
            tools.append(self.generate_image)
        if all or enable_speech_generation:
            tools.append(self.generate_speech)

        super().__init__(name="openai_tools", tools=tools, **kwargs)

    def transcribe_audio(self, audio_path: str) -> str:
        """Transcribe audio file using OpenAI's Whisper API
        Args:
            audio_path: Path to the audio file
        """
        log_debug(f"Transcribing audio from {audio_path}")
        try:
            with open(audio_path, "rb") as audio_file:
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
        prompt: str,
    ) -> ToolResult:
        """Generate images based on a text prompt.
        Args:
            prompt (str): The text prompt to generate the image from.
        """
        try:
            import base64

            extra_params = {
                "n": self.image_n,
                "size": self.image_size,
                "quality": self.image_quality,
            }
            extra_params = {k: v for k, v in extra_params.items() if v is not None}

            # Image models return base64 only and reject response_format and style, so neither is sent.
            response = OpenAIClient(api_key=self.api_key).images.generate(
                model=self.image_model,
                prompt=prompt,
                **extra_params,  # type: ignore
            )
            if not (hasattr(response, "data") and response.data):
                log_warning("OpenAI API did not return any data.")
                return ToolResult(content="Failed to generate image: No data received from API.")

            output_format = getattr(response, "output_format", None)
            mime_type = f"image/{output_format}" if isinstance(output_format, str) else "image/png"
            images: List[Image] = []
            for data in response.data:
                if not (hasattr(data, "b64_json") and data.b64_json):
                    continue
                images.append(
                    Image(
                        id=str(uuid4()),
                        content=base64.b64decode(data.b64_json),
                        mime_type=mime_type,
                        original_prompt=prompt,
                    )
                )

            if not images:
                return ToolResult(content="Failed to generate image: No content received from API.")
            content = (
                "Image generated successfully." if len(images) == 1 else f"{len(images)} images generated successfully."
            )
            return ToolResult(content=content, images=images)
        except Exception as e:
            log_error(f"Failed to generate image using {self.image_model}: {str(e)}")
            return ToolResult(content=f"Failed to generate image: {e}")

    def generate_speech(
        self,
        agent: Union[Agent, Team],
        text_input: str,
    ) -> ToolResult:  # Changed return type
        """Generate speech from text using OpenAI's Text-to-Speech API.
        Args:
            text_input (str): The text to synthesize into speech.
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
