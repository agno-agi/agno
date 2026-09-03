import json
from os import getenv, path
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union, get_args
from uuid import uuid4

import httpx

from agno.agent import Agent
from agno.media import Audio
from agno.team.team import Team
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_error, log_info

SMALLEST_TTS_URL = "https://api.smallest.ai/waves/v1/tts"
SMALLEST_VOICES_URLS = {
    "lightning_v3.1": "https://api.smallest.ai/waves/v1/lightning-v3.1/get_voices",
    "lightning_v3.1_pro": "https://api.smallest.ai/waves/v1/lightning-v3.1-pro/get_voices",
}

SmallestModel = Literal[
    "lightning_v3.1",  # 12 languages, supports cloned voices
    "lightning_v3.1_pro",  # premium voice pool, 29 languages
]
SMALLEST_MODELS = get_args(SmallestModel)

SmallestOutputFormat = Literal["wav", "mp3", "pcm", "ulaw", "alaw"]

MIME_TYPES: Dict[str, str] = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
    "pcm": "audio/wav",
    "ulaw": "audio/basic",
    "alaw": "audio/x-alaw-basic",
}


class SmallestTools(Toolkit):
    def __init__(
        self,
        voice_id: str = "magnus",
        api_key: Optional[str] = None,
        model: SmallestModel = "lightning_v3.1",
        language: str = "en",
        sample_rate: int = 24000,
        speed: float = 1.0,
        output_format: SmallestOutputFormat = "wav",
        target_directory: Optional[str] = None,
        base_url: str = SMALLEST_TTS_URL,
        enable_get_voices: bool = True,
        enable_text_to_speech: bool = True,
        all: bool = False,
        timeout: float = 30,
        **kwargs,
    ):
        self.api_key = api_key or getenv("SMALLEST_API_KEY")
        if not self.api_key:
            log_error("SMALLEST_API_KEY not set. Please set the SMALLEST_API_KEY environment variable.")

        if model not in SMALLEST_MODELS:
            raise ValueError(f"Invalid model '{model}'. Valid options are: {', '.join(SMALLEST_MODELS)}")

        self.voice_id = voice_id
        self.model = model
        self.language = language
        self.sample_rate = sample_rate
        self.speed = speed
        self.output_format = output_format
        self.target_directory = target_directory
        self.base_url = base_url
        self.timeout = timeout

        if self.target_directory:
            target_path = Path(self.target_directory)
            target_path.mkdir(parents=True, exist_ok=True)

        tools: List[Any] = []
        if all or enable_get_voices:
            tools.append(self.get_voices)
        if all or enable_text_to_speech:
            tools.append(self.text_to_speech)

        super().__init__(name="smallest_tools", tools=tools, **kwargs)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "X-Source": "agno",
        }

    def get_voices(self) -> str:
        """
        Get all the voices available for the configured Smallest AI model. The standard
        Lightning v3.1 and Lightning v3.1 Pro models have separate voice catalogs.

        Returns:
            result (str): JSON string containing a list of voices with their metadata.
        """
        try:
            response = httpx.get(
                SMALLEST_VOICES_URLS[self.model],
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()

            voices_data = response.json()
            if isinstance(voices_data, dict):
                if "voices" in voices_data:
                    voices = voices_data["voices"]
                elif "data" in voices_data:
                    voices = voices_data["data"]
                else:
                    voices = voices_data
            else:
                voices = voices_data

            if isinstance(voices, list):
                result = []
                for voice in voices:
                    if not isinstance(voice, dict):
                        continue
                    tags = voice.get("tags") or {}
                    result.append(
                        {
                            "id": voice.get("voiceId") or voice.get("voice_id") or voice.get("id"),
                            "name": voice.get("displayName") or voice.get("name"),
                            "gender": tags.get("gender") or voice.get("gender"),
                            "accent": tags.get("accent") or voice.get("accent"),
                            "languages": tags.get("language") or voice.get("languages"),
                        }
                    )
                return json.dumps(result)

            return json.dumps(voices)
        except Exception as e:
            log_error(f"Failed to fetch voices: {str(e)}")
            return f"Error: {e}"

    def _save_audio(self, audio_data: bytes) -> bytes:
        # Save to disk if target_directory exists
        if self.target_directory:
            output_filename = f"{uuid4()}.{self.output_format}"
            output_path = path.join(self.target_directory, output_filename)

            with open(output_path, "wb") as f:
                f.write(audio_data)

            log_info(f"Audio saved to: {output_path}")

        return audio_data

    def text_to_speech(self, agent: Union[Agent, Team], prompt: str, voice_id: Optional[str] = None) -> ToolResult:
        """
        Convert text to natural speech using Smallest AI Lightning models.

        Args:
            prompt (str): Text to generate audio from.
            voice_id (optional): The ID of the voice to use. If None, uses the default voice
                configured in the tool. The voice must belong to the configured model's pool.
        Returns:
            ToolResult: A ToolResult containing the generated audio or error message.
        """
        try:
            mime_type = MIME_TYPES.get(self.output_format, "audio/wav")

            payload: Dict[str, Any] = {
                "text": prompt,
                "voice_id": voice_id or self.voice_id,
                "model": self.model,
                "language": self.language,
                "sample_rate": self.sample_rate,
                "speed": self.speed,
                "output_format": self.output_format,
            }

            response = httpx.post(
                self.base_url,
                headers={
                    **self._headers(),
                    "Content-Type": "application/json",
                    "Accept": mime_type,
                },
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "audio" not in content_type and "octet-stream" not in content_type:
                raise ValueError(f"Expected audio response but got content-type '{content_type}': {response.text}")

            audio_data = self._save_audio(response.content)

            audio_artifact = Audio(
                id=str(uuid4()),
                content=audio_data,
                mime_type=mime_type,
                format=self.output_format,
                sample_rate=self.sample_rate,
            )

            return ToolResult(
                content="Audio generated successfully",
                audios=[audio_artifact],
            )

        except Exception as e:
            log_error(f"Failed to generate audio: {str(e)}")
            return ToolResult(content=f"Error: {e}")
