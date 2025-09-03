from os import getenv
from typing import Any, List, Optional, Union
from uuid import uuid4

import requests

from agno.agent import Agent
from agno.media import AudioArtifact
from agno.team.team import Team
from agno.tools import Toolkit
from agno.utils.log import logger


class DesiVocalTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: Optional[str] = "f27d74e5-ea71-4697-be3e-f04bbd80c1a8",
        **kwargs,
    ):
        self.api_key = api_key or getenv("DESI_VOCAL_API_KEY")
        if not self.api_key:
            logger.error("DESI_VOCAL_API_KEY not set. Please set the DESI_VOCAL_API_KEY environment variable.")

        self.voice_id = voice_id

        tools: List[Any] = []
        tools.append(self.get_voices)
        tools.append(self.text_to_speech)

        super().__init__(name="desi_vocal_tools", tools=tools, **kwargs)

    def get_voices(self) -> str:
        """
        Use this function to get all the voices available.
        Returns:
            result (list): A list of voices that have an ID, name and description.
        """
        try:
            url = "https://prod-api2.desivocal.com/dv/api/v0/tts_api/voices"
            response = requests.get(url)
            response.raise_for_status()

            voices_data = response.json()

            responses = []
            for voice_id, voice_info in voices_data.items():
                responses.append(
                    {
                        "id": voice_id,
                        "name": voice_info["name"],
                        "gender": voice_info["audio_gender"],
                        "type": voice_info["voice_type"],
                        "language": ", ".join(voice_info["languages"]),
                        "preview_url": next(iter(voice_info["preview_path"].values()))
                        if voice_info["preview_path"]
                        else None,
                    }
                )

            return str(responses)
        except Exception as e:
            logger.error(f"Failed to get voices: {e}")
            return f"Error: {e}"

    def text_to_speech(self, agent: Union[Agent, Team], prompt: str, voice_id: Optional[str] = None) -> str:
        """
        Use this function to generate audio from text.
        Args:
            prompt (str): The text to generate audio from.
        Returns:
            result (str): The URL of the generated audio.
        """
        try:
            url = "https://prod-api2.desivocal.com/dv/api/v0/tts_api/generate"

            payload = {
                "text": prompt,
                "voice_id": voice_id or self.voice_id,
            }

            headers = {
                "X_API_KEY": self.api_key,
                "Content-Type": "application/json",
            }

            response = requests.post(url, headers=headers, json=payload)

            response.raise_for_status()

            response_json = response.json()
            audio_url = response_json["s3_path"]

            agent.add_audio(AudioArtifact(id=str(uuid4()), url=audio_url))

            return audio_url
        except Exception as e:
            logger.error(f"Failed to generate audio: {e}")
            return f"Error: {e}"
