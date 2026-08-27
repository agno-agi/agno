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

SPEKO_BASE_URL = "https://api.speko.ai/v1"

SpekoOutputFormat = Literal["wav", "pcm"]
SPEKO_OUTPUT_FORMATS = get_args(SpekoOutputFormat)

SpekoObjective = Literal["latency", "quality", "cost", "balanced"]
SPEKO_OBJECTIVES = get_args(SpekoObjective)

# Speko normalizes every TTS provider to 16-bit mono PCM at 24 kHz
# (raw for "pcm", RIFF-wrapped for "wav"), so the sample rate is fixed.
SPEKO_SAMPLE_RATE = 24000

MIME_TYPES: Dict[str, str] = {
    "wav": "audio/wav",
    "pcm": "audio/pcm",
}


class SpekoTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        tts_model: str = "auto",
        stt_model: str = "auto",
        voice: Optional[str] = None,
        output_format: SpekoOutputFormat = "wav",
        language: Optional[str] = None,
        objective: Optional[SpekoObjective] = None,
        target_directory: Optional[str] = None,
        base_url: str = SPEKO_BASE_URL,
        enable_text_to_speech: bool = True,
        enable_transcribe_audio: bool = True,
        enable_list_voices: bool = True,
        enable_list_models: bool = False,
        all: bool = False,
        timeout: float = 30,
        **kwargs,
    ):
        self.api_key = api_key or getenv("SPEKO_API_KEY")
        if not self.api_key:
            log_error("SPEKO_API_KEY not set. Please set the SPEKO_API_KEY environment variable.")

        if output_format not in SPEKO_OUTPUT_FORMATS:
            raise ValueError(
                f"Invalid output_format '{output_format}'. Valid options are: {', '.join(SPEKO_OUTPUT_FORMATS)}"
            )

        if objective is not None and objective not in SPEKO_OBJECTIVES:
            raise ValueError(f"Invalid objective '{objective}'. Valid options are: {', '.join(SPEKO_OBJECTIVES)}")

        self.tts_model = tts_model
        self.stt_model = stt_model
        self.voice = voice
        self.output_format = output_format
        self.language = language
        self.objective = objective
        self.target_directory = target_directory
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        if self.target_directory:
            target_path = Path(self.target_directory)
            target_path.mkdir(parents=True, exist_ok=True)

        tools: List[Any] = []
        if all or enable_text_to_speech:
            tools.append(self.text_to_speech)
        if all or enable_transcribe_audio:
            tools.append(self.transcribe_audio)
        if all or enable_list_voices:
            tools.append(self.list_voices)
        if all or enable_list_models:
            tools.append(self.list_models)

        super().__init__(name="speko_tools", tools=tools, **kwargs)

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "X-Source": "agno",
        }
        if self.language:
            headers["X-Speko-Language"] = self.language
        if self.objective:
            headers["X-Speko-Objective"] = self.objective
        return headers

    def _save_audio(self, audio_data: bytes) -> bytes:
        # Save to disk if target_directory exists
        if self.target_directory:
            output_filename = f"{uuid4()}.{self.output_format}"
            output_path = path.join(self.target_directory, output_filename)

            with open(output_path, "wb") as f:
                f.write(audio_data)

            log_info(f"Audio saved to: {output_path}")

        return audio_data

    def text_to_speech(self, agent: Union[Agent, Team], prompt: str, voice: Optional[str] = None) -> ToolResult:
        """
        Convert text to natural speech using the Speko voice router. Speko routes the
        request to the best TTS provider for the configured objective and falls over
        automatically, always returning 16-bit mono audio at 24 kHz.

        Args:
            prompt (str): Text to generate audio from.
            voice (optional): The ID of the voice to use, e.g. "aura-2-thalia-en". If None,
                uses the voice configured in the tool, or lets Speko pick a provider default.
                Use the `list_voices` tool to see the available voices.
        Returns:
            ToolResult: A ToolResult containing the generated audio or error message.
        """
        try:
            mime_type = MIME_TYPES.get(self.output_format, "audio/wav")

            payload: Dict[str, Any] = {
                "model": self.tts_model,
                "input": prompt,
                "response_format": self.output_format,
            }
            if voice or self.voice:
                payload["voice"] = voice or self.voice

            response = httpx.post(
                f"{self.base_url}/audio/speech",
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
                sample_rate=SPEKO_SAMPLE_RATE,
            )

            return ToolResult(
                content="Audio generated successfully",
                audios=[audio_artifact],
            )

        except Exception as e:
            log_error(f"Failed to generate audio: {str(e)}")
            return ToolResult(content=f"Error: {e}")

    def transcribe_audio(self, audio_path: str) -> str:
        """
        Transcribe an audio file to text using the Speko voice router. Speko routes the
        request to the best speech-to-text provider for the configured objective.

        Args:
            audio_path (str): Path to the audio file to transcribe.
        Returns:
            result (str): The transcribed text, or an error message.
        """
        try:
            file_path = Path(audio_path)
            with open(file_path, "rb") as audio_file:
                response = httpx.post(
                    f"{self.base_url}/audio/transcriptions",
                    headers=self._headers(),
                    files={"file": (file_path.name, audio_file)},
                    data={"model": self.stt_model},
                    timeout=self.timeout,
                )
            response.raise_for_status()

            transcript = response.json().get("text", "")
            log_info(f"Transcribed {audio_path}: {transcript}")
            return transcript
        except Exception as e:
            log_error(f"Failed to transcribe audio: {str(e)}")
            return f"Error: {e}"

    def list_voices(self) -> str:
        """
        List the text-to-speech voices available on the Speko voice router, across
        all routable TTS providers.

        Returns:
            result (str): JSON string containing a list of voices with their metadata.
        """
        try:
            response = httpx.get(
                f"{self.base_url}/models",
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()

            models_data = response.json()
            models = models_data.get("data", []) if isinstance(models_data, dict) else models_data

            result = []
            for model in models:
                if not isinstance(model, dict):
                    continue
                if model.get("api") != "tts" or not model.get("routable"):
                    continue
                for voice in model.get("voices") or []:
                    if not isinstance(voice, dict):
                        continue
                    result.append(
                        {
                            "id": voice.get("id"),
                            "name": voice.get("name"),
                            "gender": voice.get("gender"),
                            "styles": voice.get("styles"),
                            "model": model.get("id"),
                            "provider": model.get("provider"),
                        }
                    )
            return json.dumps(result)
        except Exception as e:
            log_error(f"Failed to fetch voices: {str(e)}")
            return f"Error: {e}"

    def list_models(self, api: Optional[str] = None) -> str:
        """
        List the models available on the Speko voice router, optionally filtered by API
        stage. Any routable model ID can be pinned instead of "auto" routing.

        Args:
            api (optional): Filter by stage: "tts", "stt", or "llm". If None, lists all models.
        Returns:
            result (str): JSON string containing a list of models with their metadata.
        """
        try:
            response = httpx.get(
                f"{self.base_url}/models",
                headers=self._headers(),
                timeout=self.timeout,
            )
            response.raise_for_status()

            models_data = response.json()
            models = models_data.get("data", []) if isinstance(models_data, dict) else models_data

            result = []
            for model in models:
                if not isinstance(model, dict):
                    continue
                if api and model.get("api") != api:
                    continue
                result.append(
                    {
                        "id": model.get("id"),
                        "api": model.get("api"),
                        "provider": model.get("provider"),
                        "routable": model.get("routable"),
                        "languages": model.get("languages"),
                        "latencyMs": model.get("latencyMs"),
                        "costPerMinUsd": model.get("costPerMinUsd"),
                        "quality": model.get("quality"),
                        "qualityUnit": model.get("qualityUnit"),
                    }
                )
            return json.dumps(result)
        except Exception as e:
            log_error(f"Failed to fetch models: {str(e)}")
            return f"Error: {e}"
