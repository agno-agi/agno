import json
from base64 import b64encode
from os import getenv
from typing import Any, Dict, Optional, Union
from uuid import uuid4

from agno.agent import Agent
from agno.media import AudioArtifact
from agno.team.team import Team
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_info

try:
    import cartesia  # type: ignore
except ImportError:
    raise ImportError("`cartesia` not installed. Please install using `pip install cartesia`")


class CartesiaTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: str = "sonic-2",
        default_voice_id: str = "78ab82d5-25be-4f7d-82b3-7ad64e5b85b2",
        text_to_speech_enabled: bool = True,
        list_voices_enabled: bool = True,
        voice_localize_enabled: bool = False,
    ):
        super().__init__(name="cartesia_tools")

        self.api_key = api_key or getenv("CARTESIA_API_KEY")

        if not self.api_key:
            raise ValueError("CARTESIA_API_KEY not set. Please set the CARTESIA_API_KEY environment variable.")

        self.client = cartesia.Cartesia(api_key=self.api_key)
        self.model_id = model_id
        self.default_voice_id = default_voice_id

        if voice_localize_enabled:
            self.register(self.localize_voice)
        if text_to_speech_enabled:
            self.register(self.text_to_speech)
        if list_voices_enabled:
            self.register(self.list_voices)

    def list_voices(self) -> str:
        """List available voices from Cartesia (first page).

        Returns:
            str: JSON string containing a list of voices, each with id, name, description, and language.
        """
        try:
            voices = self.client.voices.list()

            voice_objects = voices.items if voices else None

            filtered_result = []
            if voice_objects:
                for voice in voice_objects:
                    try:
                        # Extract desired attributes from the Voice object
                        voice_data = {
                            "id": voice.id if hasattr(voice, "id") else None,
                            "name": voice.name if hasattr(voice, "name") else None,
                            "description": voice.description if hasattr(voice, "description") else None,
                            "language": voice.language if hasattr(voice, "language") else None,
                        }

                        if voice_data["id"]:  # Only add if we could get an ID
                            filtered_result.append(voice_data)
                        else:
                            log_info(f"Could not extract 'id' from voice object: {voice}")
                    except AttributeError as ae:
                        log_error(f"AttributeError accessing voice data: {ae}. Voice data: {voice}")
                        continue
                    except Exception as inner_e:
                        log_error(f"Unexpected error processing voice: {inner_e}. Voice data: {voice}")
                        continue

            return json.dumps(filtered_result, indent=4)
        except Exception as e:
            log_error(f"Error listing voices from Cartesia: {e}", exc_info=True)
            return json.dumps({"error": str(e), "detail": "Error occurred in list_voices function."})

    def localize_voice(
        self,
        name: str,
        description: str,
        language: str,
        original_speaker_gender: str,
        voice_id: Optional[str] = None,
    ) -> str:
        """Create a new voice localized to a different language.

        Args:
            name (str): The desired name for the new localized voice.
            description (str): The description for the new localized voice.
            language (str): The target language code (e.g., 'fr', 'es').
            original_speaker_gender (str): The gender of the original speaker ("male" or "female").
            voice_id (optional): The ID of an existing voice to use as the base. If None, uses the default voice ID configured in the tool. Defaults to None.

        Returns:
            str: JSON string containing the information of the newly created localized voice, including its 'id'.
        """
        localize_voice_id = voice_id or self.default_voice_id
        log_debug(f"Using voice_id '{localize_voice_id}' for localization.")

        try:
            result = self.client.voices.localize(
                voice_id=localize_voice_id,
                name=name,
                description=description,
                language=language,
                original_speaker_gender=original_speaker_gender,
            )

            if isinstance(result, dict):
                return json.dumps(result, indent=4)
            else:
                return result.model_dump_json(indent=4)

        except Exception as e:
            log_error(f"Error localizing voice with Cartesia: {e}", exc_info=True)
            return json.dumps({"error": str(e), "type": type(e).__name__})

    def text_to_speech(
        self,
        agent: Union[Agent, Team],
        transcript: str,
        voice_id: Optional[str] = None,
    ) -> str:
        """
        Convert text to speechß.
        Args:
            transcript: The text to convert to speech
            voice_id (optional): The ID of the voice to use for the text-to-speech. If None, uses the default voice ID configured in the tool. Defaults to None.

        Returns:
            str: Success or error message.
        """

        try:
            effective_voice_id = voice_id or self.default_voice_id

            log_info(f"Using voice_id: {effective_voice_id} for text_to_speech.")
            log_info(f"Using model_id: {self.model_id} for text_to_speech.")

            output_format_sample_rate = 44100
            requested_bit_rate = 128000
            mime_type = "audio/mpeg"

            output_format = {
                "container": "mp3",
                "sample_rate": output_format_sample_rate,
                "bit_rate": requested_bit_rate,
                "encoding": "mp3",
            }

            params: Dict[str, Any] = {
                "model_id": self.model_id,
                "transcript": transcript,
                "voice": {"mode": "id", "id": effective_voice_id},
                "output_format": output_format,
            }

            audio_iterator = self.client.tts.bytes(**params)
            audio_data = b"".join(chunk for chunk in audio_iterator)
            base64_audio = b64encode(audio_data).decode("utf-8")

            artifact = AudioArtifact(
                id=str(uuid4()),
                base64_audio=base64_audio,
                mime_type=mime_type,  # Hardcoded to audio/mpeg
            )
            agent.add_audio(artifact)

            return "Audio generated and attached successfully."

        except Exception as e:
            log_error(f"Error generating speech with Cartesia: {e}", exc_info=True)
            return f"Error generating speech: {e}"
