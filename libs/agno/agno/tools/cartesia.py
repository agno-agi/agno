import json
from base64 import b64encode
from os import getenv
from typing import Any, Dict, Optional, Union
from uuid import uuid4

from agno.agent import Agent
from agno.media import AudioArtifact
from agno.team.team import Team
from agno.tools import Toolkit
from agno.utils.log import logger

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
                            logger.warning(f"Could not extract 'id' from voice object: {voice}")
                    except AttributeError as ae:
                        logger.error(f"AttributeError accessing voice data: {ae}. Voice data: {voice}")
                        continue
                    except Exception as inner_e:
                        logger.error(f"Unexpected error processing voice: {inner_e}. Voice data: {voice}")
                        continue

            return json.dumps(filtered_result, indent=4)
        except Exception as e:
            logger.error(f"Error listing voices from Cartesia: {e}", exc_info=True)
            return json.dumps({"error": str(e), "detail": "Error occurred in list_voices function."})

    def localize_voice(
        self,
        voice_id: str,
        name: str,
        description: str,
        language: str,
        original_speaker_gender: str,
        dialect: Optional[str] = None,
    ) -> str:
        """Create a new voice localized to a different language.

        Args:
            voice_id (str): The ID of the voice to localize.
            name (str): The name for the new localized voice.
            description (str): The description for the new localized voice.
            language (str): The target language code.
            original_speaker_gender (str): The gender of the original speaker ("male" or "female").
            dialect (Optional[str], optional): The dialect code. Defaults to None.

        Returns:
            str: JSON string containing the localized voice information.
        """
        try:
            if dialect:
                # Call with dialect
                result = self.client.voices.localize(
                    voice_id=voice_id,
                    name=name,
                    description=description,
                    language=language,
                    original_speaker_gender=original_speaker_gender,
                    dialect=dialect,
                )
            else:
                # Call without dialect
                result = self.client.voices.localize(
                    voice_id=voice_id,
                    name=name,
                    description=description,
                    language=language,
                    original_speaker_gender=original_speaker_gender,
                )

            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error localizing voice with Cartesia: {e}")
            return json.dumps({"error": str(e)})

    def text_to_speech(
        self,
        agent: Union[Agent, Team],
        transcript: str,
    ) -> str:
        """
        Convert text to speechß.
        Args:
            agent: The agent or team to attach the audio artifact to.
            transcript: The text to convert to speech

        Returns:
            str: Success or error message.
        """

        try:
            effective_voice_id = self.default_voice_id

            logger.info(f"Using voice_id: {effective_voice_id} for text_to_speech.")
            logger.info(f"Using model_id: {self.model_id} for text_to_speech.")

            # Hardcode output format to MP3
            output_format_sample_rate = 44100
            requested_bit_rate = 128000
            mime_type = "audio/mpeg"

            output_format = {
                "container": "mp3",
                "sample_rate": output_format_sample_rate,
                "bit_rate": requested_bit_rate,
                "encoding": "mp3",
            }

            # Base parameters for the API call
            params: Dict[str, Any] = {
                "model_id": self.model_id,
                "transcript": transcript,
                "voice": {"mode": "id", "id": effective_voice_id},
                # "language": normalized_language, # Language param removed
                "output_format": output_format,
            }

            # Log parameters just before the API call for debugging
            logger.debug(f"Calling Cartesia tts.bytes with params: {json.dumps(params, indent=2)}")

            # Make the API call - v2 returns an iterator
            audio_iterator = self.client.tts.bytes(**params)

            # Concatenate the bytes from the iterator
            audio_data = b"".join(chunk for chunk in audio_iterator)

            # Encode to base64
            base64_audio = b64encode(audio_data).decode("utf-8")

            # Create and attach artifact
            artifact = AudioArtifact(
                id=str(uuid4()),
                base64_audio=base64_audio,
                mime_type=mime_type,  # Hardcoded to audio/mpeg
            )
            agent.add_audio(artifact)

            return "Audio generated and attached successfully."

        except Exception as e:
            logger.error(f"Error generating speech with Cartesia: {e}", exc_info=True)
            return f"Error generating speech: {e}"
