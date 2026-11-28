import base64
from os import getenv
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Tuple, Union, get_args
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

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionAudioParam, ChatCompletionMessageParam

# Define only types specifically needed by OpenAITools class
OpenAIVoice = Literal[
    "alloy",
    "ash",
    "ballad",
    "cedar",
    "coral",
    "echo",
    "fable",
    "marin",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
]
# Models served by /v1/audio/speech. OpenAI shuts every one of them down on
# January 6, 2027 and names no replacement on that endpoint, so speech now
# defaults to an audio chat model instead.
OpenAISpeechAPIModel = Literal[
    "tts-1",
    "tts-1-hd",
    "gpt-4o-mini-tts",
    "gpt-4o-mini-tts-2025-03-20",
    "gpt-4o-mini-tts-2025-12-15",
]
# Models that take text and return audio over /v1/chat/completions.
OpenAIAudioChatModel = Literal["gpt-audio-1.5"]
# Literal flattens nested literals, so this stays in step with the two lists above.
OpenAITTSModel = Literal[OpenAISpeechAPIModel, OpenAIAudioChatModel]
OpenAITTSFormat = Literal["mp3", "opus", "aac", "flac", "wav", "pcm"]

SPEECH_API_MODELS = frozenset(get_args(OpenAISpeechAPIModel))
# generate_speech routes to chat completions only for these, so a model it has never
# heard of keeps using /v1/audio/speech rather than being sent somewhere it cannot work.
AUDIO_CHAT_MODELS = frozenset(get_args(OpenAIAudioChatModel))
# /v1/chat/completions names raw PCM "pcm16" where /v1/audio/speech calls it "pcm".
ChatAudioFormat = Literal["mp3", "opus", "aac", "flac", "wav", "pcm16"]
_CHAT_AUDIO_FORMATS: Dict[OpenAITTSFormat, ChatAudioFormat] = {
    "mp3": "mp3",
    "opus": "opus",
    "aac": "aac",
    "flac": "flac",
    "wav": "wav",
    "pcm": "pcm16",
}

DEFAULT_TRANSCRIPTION_MODEL = "gpt-transcribe"
DEFAULT_IMAGE_MODEL = "gpt-image-2.6-sunburst"
DEFAULT_TTS_MODEL = "gpt-audio-1.5"

# Models OpenAI has announced a shutdown date for, mapped to that date and the
# replacement it recommends. Warned about at construction so a pinned model is
# flagged before the date rather than failing after it.
RETIRING_MODELS: Dict[str, Tuple[str, str]] = {
    "tts-1": ("January 6, 2027", DEFAULT_TTS_MODEL),
    "tts-1-hd": ("January 6, 2027", DEFAULT_TTS_MODEL),
    "gpt-4o-mini-tts": ("January 6, 2027", DEFAULT_TTS_MODEL),
    "gpt-4o-mini-tts-2025-03-20": ("January 6, 2027", DEFAULT_TTS_MODEL),
    "gpt-4o-mini-tts-2025-12-15": ("January 6, 2027", DEFAULT_TTS_MODEL),
    "gpt-audio": ("January 20, 2027", DEFAULT_TTS_MODEL),
    "gpt-audio-2025-08-28": ("January 20, 2027", DEFAULT_TTS_MODEL),
    "gpt-audio-mini": ("January 20, 2027", DEFAULT_TTS_MODEL),
    "gpt-audio-mini-2025-12-15": ("January 20, 2027", DEFAULT_TTS_MODEL),
    "whisper-1": ("February 26, 2027", DEFAULT_TRANSCRIPTION_MODEL),
    "gpt-4o-transcribe": ("February 26, 2027", DEFAULT_TRANSCRIPTION_MODEL),
    "gpt-4o-transcribe-diarize": ("February 26, 2027", DEFAULT_TRANSCRIPTION_MODEL),
    "gpt-4o-mini-transcribe": ("February 26, 2027", DEFAULT_TRANSCRIPTION_MODEL),
    "gpt-4o-mini-transcribe-2025-03-20": ("January 20, 2027", DEFAULT_TRANSCRIPTION_MODEL),
    "gpt-4o-mini-transcribe-2025-12-15": ("February 26, 2027", DEFAULT_TRANSCRIPTION_MODEL),
    "gpt-image-2": ("February 10, 2027", DEFAULT_IMAGE_MODEL),
    "gpt-image-2-2026-04-21": ("February 10, 2027", DEFAULT_IMAGE_MODEL),
}

_GPT_IMAGE_QUALITIES = ["auto", "low", "medium", "high"]
# The 2.5 and 2.6 generations add two quality levels above "high".
_SUNBURST_FLARE_QUALITIES = _GPT_IMAGE_QUALITIES + ["xhigh", "max"]
_IMAGE_COMPLEXITIES = ["low", "medium", "high"]
_FIXED_GPT_IMAGE_SIZES = ["auto", "1024x1024", "1536x1024", "1024x1536"]
# Sizes, qualities and complexities each known image model accepts. Models not listed
# here are passed through unchecked, and an option the model takes but this table omits
# is left for the API to validate rather than rejected locally.
# The sunburst, flare and gpt-image-2 models take custom resolutions, so their sizes are
# left out. Only sunburst and flare accept a separate planning complexity.
IMAGE_MODEL_OPTIONS: Dict[str, Dict[str, List[str]]] = {
    "gpt-image-2.6-sunburst": {"qualities": _SUNBURST_FLARE_QUALITIES, "complexities": _IMAGE_COMPLEXITIES},
    "gpt-image-2.6-flare": {"qualities": _SUNBURST_FLARE_QUALITIES, "complexities": _IMAGE_COMPLEXITIES},
    "gpt-image-2.5-sunburst": {"qualities": _SUNBURST_FLARE_QUALITIES, "complexities": _IMAGE_COMPLEXITIES},
    "gpt-image-2.5-flare": {"qualities": _SUNBURST_FLARE_QUALITIES, "complexities": _IMAGE_COMPLEXITIES},
    "gpt-image-2": {"qualities": _GPT_IMAGE_QUALITIES},
    "gpt-image-1.5": {"sizes": _FIXED_GPT_IMAGE_SIZES, "qualities": _GPT_IMAGE_QUALITIES},
    "gpt-image-1-mini": {"sizes": _FIXED_GPT_IMAGE_SIZES, "qualities": _GPT_IMAGE_QUALITIES},
}


STYLE_DEPRECATION = (
    "The image style option is deprecated and ignored: OpenAI image models reject the style parameter. "
    "It will be removed in a future release."
)

# An audio chat model answers the text it is given, so it has to be told to narrate instead.
NARRATION_INSTRUCTION = (
    "You are a text-to-speech engine. Read the user's message aloud word for word. "
    "Do not answer it, do not summarize or translate it, and do not add any words of your own."
)


def warn_if_retiring(model: Optional[str], parameter: str) -> None:
    """Log a warning when the model has an announced OpenAI shutdown date."""
    retirement = RETIRING_MODELS.get(model or "")
    if retirement is None:
        return
    shutdown_date, replacement = retirement
    log_warning(
        f"OpenAI shuts {model} down on {shutdown_date}, after which {parameter} requests naming it will fail. "
        f"Pass {parameter}='{replacement}' instead."
    )


def validate_image_options(
    model: Optional[str],
    n: int,
    size: Optional[str],
    quality: Optional[str],
    complexity: Optional[str] = None,
) -> None:
    """Raise ValueError for an image count, size, quality or complexity the model does not accept."""
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
    if complexity is not None:
        complexities = options.get("complexities")
        if complexities is None:
            raise ValueError(f"{model} does not accept a complexity. Please leave image_complexity unset.")
        if complexity not in complexities:
            raise ValueError(f"Invalid complexity for {model}. Please choose from {', '.join(complexities)}.")


def transcript_text(response: Any) -> str:
    """Pull the transcript out of a transcription response.

    Only some transcription models accept a response_format, so the request leaves it
    unset and takes the default JSON object. A model that answers with a bare string is
    passed straight through.
    """
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        text = response.get("text")
    else:
        text = getattr(response, "text", None)
    if not isinstance(text, str):
        raise ValueError(f"the transcription response carried no text (got {type(response).__name__})")
    return text


class OpenAITools(Toolkit):
    """Tools for interacting with OpenAI API.

    Args:
        api_key (str, optional): OpenAI API key. Retrieved from OPENAI_API_KEY env variable if not provided.
        enable_transcription (bool): Enable audio transcription functionality. Default is True.
        enable_image_generation (bool): Enable image generation functionality. Default is True.
        enable_speech_generation (bool): Enable speech generation functionality. Default is True.
        all (bool): Enable all tools. Overrides individual flags when True. Default is False.
        transcription_model (str): Model to use for transcription. Default is "gpt-transcribe".
        text_to_speech_voice (OpenAIVoice): Voice to use for TTS. Default is "alloy". Which voices a
            model accepts depends on the endpoint it is served by, and OpenAI's own reference and SDK
            disagree on the chat completions list, so the voice is passed through for the API to
            accept or reject rather than being checked here.
        text_to_speech_model (str): Model to use for TTS. Default is "gpt-audio-1.5", which is served
            by the chat completions endpoint. The /v1/audio/speech models ("tts-1", "tts-1-hd",
            "gpt-4o-mini-tts") are still accepted and routed to that endpoint, but OpenAI shuts
            all of them down on January 6, 2027.
        text_to_speech_format (OpenAITTSFormat): Audio format for TTS. Default is "mp3".
        image_model (str, optional): Model to use for image generation. Default is "gpt-image-2.6-sunburst".
        image_quality (str, optional): Quality setting for image generation.
        image_size (str, optional): Size setting for image generation, e.g. "1024x1024" or "auto".
            The sunburst, flare and gpt-image-2 models also accept custom resolutions.
        image_complexity (str, optional): Planning effort for image generation, one of "low", "medium"
            or "high". Only the sunburst and flare models accept it; they default to "high".
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
        transcription_model: str = DEFAULT_TRANSCRIPTION_MODEL,
        text_to_speech_voice: OpenAIVoice = "alloy",
        text_to_speech_model: Union[OpenAITTSModel, str] = DEFAULT_TTS_MODEL,
        text_to_speech_format: OpenAITTSFormat = "mp3",
        image_model: Optional[str] = DEFAULT_IMAGE_MODEL,
        image_quality: Optional[str] = None,
        image_size: Optional[str] = None,
        image_style: Optional[Literal["vivid", "natural"]] = None,
        image_n: int = 1,
        # Keyword-only, and after image_n, so the positional slots callers already use do not move.
        *,
        image_complexity: Optional[Literal["low", "medium", "high"]] = None,
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
        self.image_complexity = image_complexity
        self.image_n = image_n
        if all or enable_transcription:
            warn_if_retiring(transcription_model, "transcription_model")
        if all or enable_speech_generation:
            warn_if_retiring(text_to_speech_model, "text_to_speech_model")
        if all or enable_image_generation:
            validate_image_options(image_model, image_n, image_size, image_quality, image_complexity)
            warn_if_retiring(image_model, "image_model")
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
        """Transcribe audio file using OpenAI's transcription API
        Args:
            audio_path: Path to the audio file
        """
        log_debug(f"Transcribing audio from {audio_path}")
        try:
            with open(audio_path, "rb") as audio_file:
                # response_format is left unset: several transcription models accept
                # only the default JSON object, so the transcript is read off that.
                response = OpenAIClient(api_key=self.api_key).audio.transcriptions.create(
                    model=self.transcription_model,
                    file=audio_file,
                )
            transcript = transcript_text(response)
        except Exception as e:  # type: ignore[return]
            log_error(f"Failed to transcribe audio: {str(e)}")
            return f"Failed to transcribe audio: {str(e)}"

        log_debug(f"Transcript: {transcript}")
        return transcript

    def generate_image(
        self,
        prompt: str,
    ) -> ToolResult:
        """Generate images based on a text prompt.
        Args:
            prompt (str): The text prompt to generate the image from.
        """
        try:
            extra_params: Dict[str, Any] = {
                "n": self.image_n,
                "size": self.image_size,
                "quality": self.image_quality,
            }
            extra_params = {k: v for k, v in extra_params.items() if v is not None}
            # complexity is newer than the openai floor this package supports (>=1.106.0),
            # so it goes in the request body directly rather than as a named argument.
            if self.image_complexity is not None:
                extra_params["extra_body"] = {"complexity": self.image_complexity}

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

    def _speech_from_speech_api(self, client: OpenAIClient, text_input: str) -> bytes:
        """Synthesize text with a /v1/audio/speech model."""
        response = client.audio.speech.create(
            model=self.tts_model,
            voice=self.tts_voice,
            input=text_input,
            response_format=self.tts_format,
        )
        return response.content

    def _speech_from_audio_chat(self, client: OpenAIClient, text_input: str) -> bytes:
        """Synthesize text with an audio chat model, which returns base64 audio."""
        audio_param: "ChatCompletionAudioParam" = {
            "voice": self.tts_voice,
            "format": _CHAT_AUDIO_FORMATS[self.tts_format],
        }
        messages: List["ChatCompletionMessageParam"] = [
            {"role": "system", "content": NARRATION_INSTRUCTION},
            {"role": "user", "content": text_input},
        ]
        completion = client.chat.completions.create(
            model=self.tts_model,
            modalities=["text", "audio"],
            audio=audio_param,
            messages=messages,
        )
        audio = completion.choices[0].message.audio
        data = getattr(audio, "data", None)
        if not data:
            raise ValueError(f"{self.tts_model} returned no audio data.")
        return base64.b64decode(data)

    def generate_speech(
        self,
        agent: Union[Agent, Team],
        text_input: str,
    ) -> ToolResult:  # Changed return type
        """Generate speech from text using OpenAI's audio models.
        Args:
            text_input (str): The text to synthesize into speech.
        """
        try:
            client = OpenAIClient(api_key=self.api_key)
            if self.tts_model in AUDIO_CHAT_MODELS:
                audio_data = self._speech_from_audio_chat(client, text_input)
            else:
                audio_data = self._speech_from_speech_api(client, text_input)

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
            log_error(f"Failed to generate speech using {self.tts_model}: {str(e)}")
            return ToolResult(content=f"Failed to generate speech: {str(e)}")
