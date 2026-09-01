from os import getenv
from typing import Any, Dict, List, Literal, Optional, Union, get_args
from uuid import uuid4

import httpx

from agno.agent import Agent
from agno.media import Audio
from agno.team.team import Team
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_error, log_info

GandrAudioResponseFormat = Literal[
    "mp3",  # default, MPEG audio
    "wav",  # WAV container
    "pcm",  # headerless signed 16 bit little endian mono samples at 24000 Hz
]

GANDR_AUDIO_RESPONSE_FORMATS = get_args(GandrAudioResponseFormat)

GANDR_VOICES = [
    "gandr-mia",
    "gandr-ava",
    "gandr-jenny",
    "gandr-dane",
    "gandr-leo",
    "gandr-lewis",
]

MAX_INPUT_CHARACTERS = 2000

MIME_TYPES: Dict[str, str] = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
}

# pcm is returned headerless, so the sample rate travels on the artifact instead.
PCM_SAMPLE_RATE = 24000


class GandrTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: str = "tts-1",
        default_voice: str = "gandr-mia",
        response_format: GandrAudioResponseFormat = "mp3",
        base_url: str = "https://tts.gandr.ai",
        timeout: float = 60.0,
        enable_text_to_speech: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("GANDR_API_KEY")

        if not self.api_key:
            raise ValueError("GANDR_API_KEY not set. Please set the GANDR_API_KEY environment variable.")

        if default_voice not in GANDR_VOICES:
            raise ValueError(f"Invalid voice '{default_voice}'. Valid options are: {', '.join(GANDR_VOICES)}")

        if response_format not in GANDR_AUDIO_RESPONSE_FORMATS:
            raise ValueError(
                f"Invalid response_format '{response_format}'. "
                f"Valid options are: {', '.join(GANDR_AUDIO_RESPONSE_FORMATS)}"
            )

        self.model_id = model_id
        self.default_voice = default_voice
        self.response_format: GandrAudioResponseFormat = response_format
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        tools: List[Any] = []
        if all or enable_text_to_speech:
            tools.append(self.text_to_speech)

        super().__init__(name="gandr_tools", tools=tools, **kwargs)

    def text_to_speech(
        self,
        agent: Union[Agent, Team],
        text: str,
        voice: Optional[str] = None,
        response_format: Optional[GandrAudioResponseFormat] = None,
    ) -> ToolResult:
        """
        Convert text to speech.

        Args:
            text: The text to convert to speech. At most 2000 characters per request.
            voice (optional): The voice to use. One of gandr-mia, gandr-ava, gandr-jenny, gandr-dane, gandr-leo, gandr-lewis. If None, uses the default voice configured in the tool. Defaults to None.
            response_format (optional): The audio format: mp3, wav, or pcm. pcm is headerless signed 16 bit little endian mono samples at 24000 Hz. If None, uses the default format configured in the tool. Defaults to None.

        Returns:
            ToolResult: A ToolResult containing the generated audio or error message.
        """
        if not text.strip():
            return ToolResult(content="Error generating speech: input text is empty.")

        if len(text) > MAX_INPUT_CHARACTERS:
            return ToolResult(
                content=(
                    f"Error generating speech: input is {len(text)} characters, "
                    f"the limit is {MAX_INPUT_CHARACTERS} characters per request. "
                    "Split the text into shorter requests."
                )
            )

        effective_voice = voice or self.default_voice
        if effective_voice not in GANDR_VOICES:
            return ToolResult(
                content=(
                    f"Error generating speech: invalid voice '{effective_voice}'. "
                    f"Valid options are: {', '.join(GANDR_VOICES)}"
                )
            )

        effective_format = response_format or self.response_format
        if effective_format not in GANDR_AUDIO_RESPONSE_FORMATS:
            return ToolResult(
                content=(
                    f"Error generating speech: invalid response_format '{effective_format}'. "
                    f"Valid options are: {', '.join(GANDR_AUDIO_RESPONSE_FORMATS)}"
                )
            )

        try:

            log_info(f"Using voice: {effective_voice} for text_to_speech.")
            log_info(f"Using model: {self.model_id} and response_format: {effective_format} for text_to_speech.")

            response = httpx.post(
                f"{self.base_url}/v1/audio/speech",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model_id,
                    "input": text,
                    "voice": effective_voice,
                    "response_format": effective_format,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "audio" not in content_type and "octet-stream" not in content_type:
                raise ValueError(f"Expected audio response but got content-type '{content_type}': {response.text}")

            audio_data = response.content

            # Create AudioArtifact
            artifact_kwargs: Dict[str, Any] = {}
            if effective_format == "pcm":
                artifact_kwargs["sample_rate"] = PCM_SAMPLE_RATE

            audio_artifact = Audio(
                id=str(uuid4()),
                content=audio_data,
                mime_type=MIME_TYPES[effective_format],
                format=effective_format,
                **artifact_kwargs,
            )

            return ToolResult(
                content="Audio generated and attached successfully.",
                audios=[audio_artifact],
            )

        except Exception as e:
            log_error(f"Error generating speech with Gandr: {str(e)}")
            return ToolResult(content=f"Error generating speech: {e}")
