from os import getenv
from typing import Any, List, Literal, Optional, Union
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

GANDR_VOICES = [
    "gandr-mia",
    "gandr-ava",
    "gandr-jenny",
    "gandr-dane",
    "gandr-leo",
    "gandr-lewis",
]

MAX_INPUT_CHARACTERS = 2000

MIME_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "pcm": "audio/pcm",
}


class GandrTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: str = "tts-1",
        default_voice: str = "gandr-mia",
        response_format: GandrAudioResponseFormat = "mp3",
        base_url: str = "https://tts.gandr.ai",
        timeout: Optional[float] = None,
        enable_text_to_speech: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("GANDR_API_KEY")

        if not self.api_key:
            raise ValueError("GANDR_API_KEY not set. Please set the GANDR_API_KEY environment variable.")

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
        if len(text) > MAX_INPUT_CHARACTERS:
            return ToolResult(
                content=(
                    f"Error generating speech: input is {len(text)} characters, "
                    f"the limit is {MAX_INPUT_CHARACTERS} characters per request. "
                    "Split the text into shorter requests."
                )
            )

        try:
            effective_voice = voice or self.default_voice
            effective_format = response_format or self.response_format

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

            # The response body streams; httpx reads the full body into bytes here.
            audio_data = response.content

            # Create AudioArtifact
            audio_artifact = Audio(
                id=str(uuid4()),
                content=audio_data,
                mime_type=MIME_TYPES.get(effective_format, "audio/mpeg"),
            )

            return ToolResult(
                content="Audio generated and attached successfully.",
                audios=[audio_artifact],
            )

        except Exception as e:
            log_error(f"Error generating speech with Gandr: {str(e)}")
            return ToolResult(content=f"Error generating speech: {e}")
