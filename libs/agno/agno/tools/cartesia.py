import json
from os import getenv
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4

from agno.agent import Agent
from agno.media import Audio
from agno.team.team import Team
from agno.tools import Toolkit
from agno.tools.function import ToolResult
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
        text_to_speech: bool = True,
        list_voices: bool = True,
        localize_voice: bool = False,
        all: bool = False,
        **kwargs,
    ):
        # Backwards compat: enable_X -> X
        if "enable_text_to_speech" in kwargs:
            text_to_speech = kwargs.pop("enable_text_to_speech")
        if "enable_list_voices" in kwargs:
            list_voices = kwargs.pop("enable_list_voices")
        if "enable_localize_voice" in kwargs:
            localize_voice = kwargs.pop("enable_localize_voice")

        self.api_key = api_key or getenv("CARTESIA_API_KEY")

        if not self.api_key:
            raise ValueError("CARTESIA_API_KEY not set. Please set the CARTESIA_API_KEY environment variable.")

        self.client = cartesia.Cartesia(api_key=self.api_key)
        self.model_id = model_id
        self.default_voice_id = default_voice_id

        tools: List[Callable] = []
        if all or localize_voice:
            tools.append(self.localize_voice)
        if all or text_to_speech:
            tools.append(self.cartesia_text_to_speech)
        if all or list_voices:
            tools.append(self.list_voices)

        super().__init__(name="cartesia_tools", tools=tools, **kwargs)

    def list_voices(self) -> str:
        """List available voices from Cartesia (first page).

        Returns:
            str: JSON string containing a list of voices, each with id, name, description, and language.
        """
        try:
            voices = self.client.voices.list()

            voice_objects = list(voices) if voices else None

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
                    except AttributeError as e:
                        log_error(f"AttributeError accessing voice data. Voice data: {voice}: {str(e)}")
                        continue
                    except Exception as e:
                        log_error(f"Unexpected error processing voice. Voice data: {voice}: {str(e)}")
                        continue

            return json.dumps(filtered_result, indent=4)
        except Exception as e:
            log_error(f"Error listing voices from Cartesia: {str(e)}")
            return json.dumps({"error": str(e), "detail": "Error occurred in list_voices function."})

    def localize_voice(
        self,
        name: str,
        description: str,
        language: str,
        original_speaker_gender: str,
        accent: str = "neutral",
        voice_id: Optional[str] = None,
    ) -> str:
        """Create a new voice localized to a different language.

        Args:
            name: The desired name for the new localized voice.
            description: The description for the new localized voice.
            language: The target language code (e.g., 'fr', 'es').
            original_speaker_gender: The gender of the original speaker ("male" or "female").
            accent: The accent for the localized voice. Defaults to "neutral".
            voice_id: The ID of an existing voice to use as the base. Defaults to the configured default.

        Returns:
            JSON with the newly created localized voice info including its id.
        """
        localize_voice_id = voice_id or self.default_voice_id
        log_debug(f"Using voice_id '{localize_voice_id}' for localization.")

        try:
            result = self.client.voices.localize(
                voice_id=localize_voice_id,
                name=name,
                description=description,
                language=language,  # type: ignore[arg-type]
                original_speaker_gender=original_speaker_gender,  # type: ignore[arg-type]
                accent=accent,  # type: ignore[arg-type]
            )

            if isinstance(result, dict):
                return json.dumps(result, indent=4)
            else:
                return result.model_dump_json(indent=4)

        except Exception as e:
            log_error(f"Error localizing voice with Cartesia: {str(e)}")
            return json.dumps({"error": str(e), "type": type(e).__name__})

    def cartesia_text_to_speech(
        self,
        agent: Union[Agent, Team],
        transcript: str,
        voice_id: Optional[str] = None,
    ) -> ToolResult:
        """Convert text to speech.

        Args:
            transcript: The text to convert to speech.
            voice_id: The ID of the voice to use. Defaults to the configured default.

        Returns:
            ToolResult containing the generated audio or error message.
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

            # Create AudioArtifact
            audio_artifact = Audio(
                id=str(uuid4()),
                content=audio_data,
                mime_type=mime_type,  # Hardcoded to audio/mpeg
            )

            return ToolResult(
                content="Audio generated and attached successfully.",
                audios=[audio_artifact],
            )

        except Exception as e:
            log_error(f"Error generating speech with Cartesia: {str(e)}")
            return ToolResult(content=f"Error generating speech: {e}")
