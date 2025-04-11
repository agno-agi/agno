import datetime
import json
from os import getenv
from pathlib import Path
from typing import IO, Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from cartesia import Cartesia  # type: ignore
except ImportError:
    raise ImportError("`cartesia` not installed. Please install using `pip install cartesia`")


class CartesiaTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        text_to_speech_enabled: bool = True,
        text_to_speech_streaming_enabled: bool = True,
        list_voices_enabled: bool = True,
        voice_get_enabled: bool = True,
        voice_clone_enabled: bool = False,
        voice_delete_enabled: bool = False,
        voice_update_enabled: bool = False,
        voice_localize_enabled: bool = False,
        voice_mix_enabled: bool = False,
        voice_create_enabled: bool = False,
        voice_changer_enabled: bool = False,
        save_audio_enabled: bool = True,
        batch_processing_enabled: bool = True,
        infill_enabled: bool = False,
        api_status_enabled: bool = False,
        datasets_enabled: bool = False,
    ):
        super().__init__(name="cartesia_tools")

        self.api_key = api_key or getenv("CARTESIA_API_KEY")

        if not self.api_key:
            raise ValueError("CARTESIA_API_KEY not set. Please set the CARTESIA_API_KEY environment variable.")

        self.client = Cartesia(api_key=self.api_key)

        # Set default output directory for audio files
        self.output_dir = Path("tmp/audio_output")

        # Ensure the directory exists
        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)

        if voice_clone_enabled:
            self.register(self.clone_voice)
        if voice_delete_enabled:
            self.register(self.delete_voice)
        if voice_update_enabled:
            self.register(self.update_voice)
        if voice_get_enabled:
            self.register(self.get_voice)
        if voice_localize_enabled:
            self.register(self.localize_voice)
        if voice_mix_enabled:
            self.register(self.mix_voices)
        if voice_create_enabled:
            self.register(self.create_voice)
        if voice_changer_enabled:
            self.register(self.change_voice)
        if text_to_speech_enabled:
            self.register(self.text_to_speech)
        if text_to_speech_streaming_enabled:
            self.register(self.text_to_speech_stream)
        if infill_enabled:
            self.register(self.infill_audio)
        if api_status_enabled:
            self.register(self.get_api_status)
        if datasets_enabled:
            self.register(self.list_datasets)
            self.register(self.create_dataset)
            self.register(self.get_dataset)
            self.register(self.update_dataset)
            self.register(self.delete_dataset)
            self.register(self.list_dataset_files)
        if list_voices_enabled:
            self.register(self.list_voices)
        if save_audio_enabled:
            self.register(self.save_audio_to_file)
        if batch_processing_enabled:
            self.register(self.batch_text_to_speech)

    def _get_valid_voice_id(self, voice_id: Optional[str], language: str) -> str:
        """
        Validates the provided voice ID or finds a default one for the language.
        Args:
            voice_id: The voice ID provided by the user.
            language: The language code (normalized).
        Returns:
            A valid voice ID.
        Raises:
            ValueError: If no suitable voice can be found.
        """
        if voice_id:
            # Basic check if the provided ID looks valid (UUID format) - refine as needed
            # In a real scenario, you might want to validate against self.client.voices.get(voice_id=voice_id)
            # but that adds an extra API call. For now, we assume if provided, it might be valid.
            logger.debug(f"Using provided voice_id: {voice_id}")
            return voice_id

        logger.debug(f"No voice_id provided, attempting to find default for language: {language}")
        try:
            # Use the public list_voices method which returns JSON string of a list
            voices_response_str = self.list_voices(
                language=language
            )  # language filter might need adjustment based on list_voices impl.
            voices_data = json.loads(voices_response_str)  # voices_data is now the list

            # Ensure voices_data is a list
            if not isinstance(voices_data, list):
                # Log the error case before raising
                logger.error(
                    f"Unexpected type for voices_data. Expected list, got {type(voices_data)}. Content: {voices_data}"
                )
                raise ValueError(f"Expected a list of voices from list_voices, but got {type(voices_data)}")

            # Filter voices by language if the list_voices method doesn't already do it
            # Note: The current list_voices implementation doesn't filter by language.
            # We might need to adjust list_voices or filter here if language-specific defaults are needed.
            # For now, just pick the first available voice.
            available_voices = voices_data  # Use the list directly

            if available_voices:
                # Ensure the first voice has an 'id' key
                first_voice = available_voices[0]
                if isinstance(first_voice, dict) and "id" in first_voice and first_voice["id"]:
                    default_voice_id = first_voice["id"]
                    logger.info(f"Using default voice_id: {default_voice_id} for language {language}")
                    return default_voice_id
                else:
                    logger.error(f"First voice found is malformed or missing an ID: {first_voice}")
                    raise ValueError(f"First voice found for language {language} is missing an ID or malformed.")
            else:
                logger.warning(f"No voices found after parsing list_voices response for language: {language}")
                raise ValueError(f"No voices found for language: {language}")
        except Exception as e:
            logger.error(f"Failed to get a default voice ID for language {language}: {e}", exc_info=True)
            raise ValueError(
                f"Could not automatically determine a voice ID for language: {language}. Please provide one."
            ) from e

    def clone_voice(
        self,
        name: str,
        audio_file_path: str,
        description: Optional[str] = None,
        language: Optional[str] = None,
        mode: str = "stability",
        enhance: bool = False,
        transcript: Optional[str] = None,
    ) -> str:
        """Clone a voice using an audio sample.

        Args:
            name (str): Name for the cloned voice.
            audio_file_path (str): Path to the audio file for voice cloning.
            description (Optional[str], optional): Description of the voice. Defaults to None.
            language (Optional[str], optional): The language of the voice. Defaults to None.
            mode (str, optional): Cloning mode ("similarity" or "stability"). Defaults to "stability".
            enhance (bool, optional): Whether to enhance the clip. Defaults to False.
            transcript (Optional[str], optional): Transcript of words in the audio. Defaults to None.

        Returns:
            str: JSON string containing the cloned voice information.
        """
        try:
            with open(audio_file_path, "rb") as file:
                params = {"name": name, "clip": file, "mode": mode, "enhance": enhance}

                if description:
                    params["description"] = description

                if language:
                    params["language"] = language

                if transcript:
                    params["transcript"] = transcript

                result = self.client.voices.clone(**params)
                return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error cloning voice with Cartesia: {e}")
            return json.dumps({"error": str(e)})

    def delete_voice(self, voice_id: str) -> str:
        """Delete a voice from Cartesia.

        Args:
            voice_id (str): The ID of the voice to delete.

        Returns:
            str: JSON string containing the result of the operation.
        """
        try:
            result = self.client.voices.delete(id=voice_id)
            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error deleting voice from Cartesia: {e}")
            return json.dumps({"error": str(e)})

    def update_voice(self, voice_id: str, name: str, description: str) -> str:
        """Update voice information in Cartesia.

        Args:
            voice_id (str): The ID of the voice to update.
            name (str): The new name for the voice.
            description (str): The new description for the voice.

        Returns:
            str: JSON string containing the updated voice information.
        """
        try:
            result = self.client.voices.update(id=voice_id, name=name, description=description)
            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error updating voice in Cartesia: {e}")
            return json.dumps({"error": str(e)})

    def get_voice(self, voice_id: str) -> str:
        """Get information about a specific voice.

        Args:
            voice_id (str): The ID of the voice to get information about.

        Returns:
            str: JSON string containing the voice information.
        """
        try:
            result = self.client.voices.get(id=voice_id)
            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error getting voice information from Cartesia: {e}")
            return json.dumps({"error": str(e)})

    def list_voices(self, language: Optional[str] = None, tag_filter: Optional[List[str]] = None) -> str:
        """List all available voices in Cartesia.

        Returns:
            str: JSON string containing the list of available voices.
        """
        try:
            result = self.client.voices.list()

            # Filter to only include id and description for each voice
            filtered_result = []
            for voice in result:
                # Attempt to access attributes assuming it might be an object
                try:
                    voice_id = voice.id if hasattr(voice, "id") else voice.get("id")
                    description = voice.description if hasattr(voice, "description") else voice.get("description")
                    if voice_id:  # Only add if we could get an ID
                        filtered_voice = {"id": voice_id, "description": description}
                        filtered_result.append(filtered_voice)
                    else:
                        logger.warning(f"Could not extract 'id' from voice object/dict: {voice}")
                except AttributeError as ae:
                    logger.error(f"AttributeError accessing voice data: {ae}. Voice data: {voice}")
                    # Re-raise or handle differently if needed, for now just log and skip
                    continue  # Skip this voice if attribute access fails fundamentally
                except Exception as inner_e:
                    logger.error(f"Unexpected error processing voice: {inner_e}. Voice data: {voice}")
                    continue  # Skip this voice

            return json.dumps(filtered_result, indent=4)
        except Exception as e:
            logger.error(
                f"Error listing voices from Cartesia: {e}", exc_info=True
            )  # Add exc_info=True for full traceback
            # Return error JSON consistent with the pattern
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
            params = {
                "voice_id": voice_id,
                "name": name,
                "description": description,
                "language": language,
                "original_speaker_gender": original_speaker_gender,
            }

            if dialect:
                params["dialect"] = dialect

            result = self.client.voices.localize(**params)
            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error localizing voice with Cartesia: {e}")
            return json.dumps({"error": str(e)})

    def mix_voices(self, voices: List[Dict[str, Any]]) -> str:
        """Mix multiple voices together.

        Args:
            voices (List[Dict[str, Any]]): List of voice objects with "id" and "weight" keys.

        Returns:
            str: JSON string containing the mixed voice information.
        """
        try:
            result = self.client.voices.mix(voices=voices)
            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error mixing voices with Cartesia: {e}")
            return json.dumps({"error": str(e)})

    def create_voice(
        self,
        name: str,
        description: str,
        embedding: List[float],
        language: Optional[str] = None,
        base_voice_id: Optional[str] = None,
    ) -> str:
        """Create a voice from raw features.

        Args:
            name (str): The name for the new voice.
            description (str): The description for the new voice.
            embedding (List[float]): The voice embedding.
            language (Optional[str], optional): The language code. Defaults to None.
            base_voice_id (Optional[str], optional): The ID of the base voice. Defaults to None.

        Returns:
            str: JSON string containing the created voice information.
        """
        try:
            params = {"name": name, "description": description, "embedding": embedding}

            if language:
                params["language"] = language

            if base_voice_id:
                params["base_voice_id"] = base_voice_id

            result = self.client.voices.create(**params)
            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error creating voice with Cartesia: {e}")
            return json.dumps({"error": str(e)})

    def change_voice(
        self,
        audio_file_path: str,
        voice_id: str,
        output_format_container: str,
        output_format_sample_rate: int,
        output_format_encoding: Optional[str] = None,
        output_format_bit_rate: Optional[int] = None,
    ) -> str:
        """Change the voice in an audio file.

        Args:
            audio_file_path (str): Path to the audio file to change.
            voice_id (str): The ID of the target voice.
            output_format_container (str): The format container for the output audio.
            output_format_sample_rate (int): The sample rate for the output audio.
            output_format_encoding (Optional[str], optional): The encoding for raw/wav containers.
            output_format_bit_rate (Optional[int], optional): The bit rate for mp3 containers.

        Returns:
            str: JSON string containing the result information.
        """
        try:
            with open(audio_file_path, "rb") as file:
                params = {
                    "clip": file,
                    "voice_id": voice_id,
                    "output_format_container": output_format_container,
                    "output_format_sample_rate": output_format_sample_rate,
                }

                if output_format_encoding:
                    params["output_format_encoding"] = output_format_encoding

                if output_format_bit_rate:
                    params["output_format_bit_rate"] = output_format_bit_rate

                result = self.client.voice_changer.bytes(**params)
                return json.dumps({"success": True, "result": str(result)[:100] + "..."}, indent=4)
        except Exception as e:
            logger.error(f"Error changing voice with Cartesia: {e}")
            return json.dumps({"error": str(e)})

    def text_to_speech(
        self,
        transcript: str,
        model_id: str = "sonic-2",
        voice_id: Optional[str] = None,
        language: str = "en",
        output_format_container: str = "mp3",
        output_format_sample_rate: int = 44100,
        output_format_bit_rate: int = 128000,
        output_format_encoding: Optional[str] = None,
        output_path: Optional[str] = None,
        duration: Optional[float] = None,
        save_to_file: bool = True,
        output_filename: Optional[str] = None,
        voice_experimental_controls_speed: Optional[str] = None,
        voice_experimental_controls_emotion: Optional[List[str]] = None,
    ) -> str:
        """
        Convert text to speech using the Cartesia API.
        NOTE: Experimental controls (speed, emotion) might be ignored by the underlying non-streaming API call.

        Args:
            transcript: The text to convert to speech
            model_id: The ID of the TTS model to use. Defaults to "sonic-2".
            voice_id: The ID of the voice to use
            language: The language code (e.g., "en" for English)
            output_format_container: The format container ("mp3", "wav", "raw")
            output_format_sample_rate: The sample rate (e.g., 44100)
            output_format_bit_rate: The bit rate for MP3 formats (e.g., 128000)
            output_format_encoding: The encoding format (e.g., "mp3" for MP3, "pcm_s16le" for WAV)
            output_path: The path to save the audio file (default: None - saves to default location)
            duration: The duration of the audio (optional)
            save_to_file: Whether to save the audio to file
            output_filename: The filename to save to (without path)
            voice_experimental_controls_speed: (Optional) Speed control - may be ignored.
            voice_experimental_controls_emotion: (Optional) Emotion control - may be ignored.


        Returns:
            str: JSON string containing the result information
        """
        try:
            # Normalize language code - API expects "en" not "en-US"
            normalized_language = language.split("-")[0] if "-" in language else language

            # Ensure we have a valid voice ID *before* building params
            valid_voice_id = self._get_valid_voice_id(voice_id, normalized_language)
            logger.info(f"Using voice_id: {valid_voice_id} for text_to_speech.")
            logger.info(f"Using model_id: {model_id} for text_to_speech.")  # Log model ID

            # Log if experimental controls were passed but will be ignored
            if voice_experimental_controls_speed or voice_experimental_controls_emotion:
                logger.warning(
                    "Experimental controls (speed/emotion) were provided but might be ignored by the tts.bytes method."
                )

            # Create proper output_format based on container type
            output_format: Dict[str, Any]
            requested_bit_rate = output_format_bit_rate or 128000  # Use provided or default

            if output_format_container == "mp3":
                # Cap MP3 bitrate at 192kbps to avoid API errors for unsupported high values
                capped_bit_rate = min(requested_bit_rate, 192000)
                if requested_bit_rate > 192000:
                    logger.warning(
                        f"Requested MP3 bit rate {requested_bit_rate} exceeds supported limit. Capping at {capped_bit_rate}."
                    )

                output_format = {
                    "container": "mp3",
                    "sample_rate": output_format_sample_rate,
                    "bit_rate": capped_bit_rate,  # Use capped value
                    "encoding": output_format_encoding or "mp3",  # API likely requires encoding even for mp3
                }
            elif output_format_container in ["wav", "raw"]:
                encoding = output_format_encoding or "pcm_s16le"
                output_format = {
                    "container": output_format_container,
                    "sample_rate": output_format_sample_rate,
                    "encoding": encoding,
                }
            else:
                output_format = {
                    "container": output_format_container,
                    "sample_rate": output_format_sample_rate,
                    "encoding": output_format_encoding or "pcm_s16le",
                }
                if output_format_bit_rate:
                    output_format["bit_rate"] = output_format_bit_rate

            # Base parameters for the API call
            params: Dict[str, Any] = {
                "model_id": model_id,
                "transcript": transcript,
                "voice": {"mode": "id", "id": valid_voice_id},
                "language": normalized_language,
                "output_format": output_format,
            }

            # Add optional duration parameter if provided
            if duration is not None:
                params["duration"] = duration

            # Log parameters just before the API call for debugging
            logger.debug(f"Calling Cartesia tts.bytes with params: {json.dumps(params, indent=2)}")

            # Make the API call - v2 returns an iterator
            audio_iterator = self.client.tts.bytes(**params)

            # Concatenate the bytes from the iterator
            audio_data = b"".join(chunk for chunk in audio_iterator)

            total_bytes = len(audio_data)  # Now len() should work on the bytes object

            # Save to file if requested
            if output_path or save_to_file:
                file_path = None

                if output_path:
                    file_path = self.output_dir / Path(output_path).name  # Use Path object correctly
                else:
                    if not output_filename:
                        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                        output_filename = f"tts_{timestamp}.{output_format_container}"
                    file_path = self.output_dir / output_filename

                # Ensure directory exists
                file_path.parent.mkdir(parents=True, exist_ok=True)

                with open(file_path, "wb") as f:
                    f.write(audio_data)

                return json.dumps({"success": True, "file_path": str(file_path), "total_bytes": total_bytes}, indent=4)
            else:
                # Even when not saving to file, return a JSON string not binary data
                return json.dumps(
                    {"success": True, "total_bytes": total_bytes, "data": "Binary audio data (not displayed)"}, indent=4
                )

        except Exception as e:
            logger.error(f"Error generating speech with Cartesia: {e}", exc_info=True)  # Add exc_info
            return json.dumps({"error": str(e)})

    def infill_audio(
        self,
        transcript: str,
        voice_id: str,
        model_id: str = "sonic-2",
        language: str = "en",
        left_audio_path: Optional[str] = None,
        right_audio_path: Optional[str] = None,
        output_format_container: str = "wav",
        output_format_sample_rate: int = 44100,
        output_format_encoding: Optional[str] = None,
        output_format_bit_rate: Optional[int] = None,
        voice_experimental_controls_speed: Optional[str] = None,
        voice_experimental_controls_emotion: Optional[List[str]] = None,
        output_path: Optional[str] = None,
        save_to_file: bool = True,
        output_filename: Optional[str] = None,
    ) -> str:
        """Generate audio that smoothly connects two existing audio segments.

        Args:
            transcript (str): The infill text to generate.
            voice_id (str): The ID of the voice to use.
            model_id (str): The ID of the model to use. Defaults to "sonic-2".
            language (str): The language code. Defaults to "en".
            left_audio_path (Optional[str], optional): Path to the left audio file. Defaults to None.
            right_audio_path (Optional[str], optional): Path to the right audio file. Defaults to None.
            output_format_container (str, optional): The format container. Defaults to "wav".
            output_format_sample_rate (int, optional): The sample rate. Defaults to 44100.
            output_format_encoding (Optional[str], optional): The encoding for raw/wav. Defaults to None.
            output_format_bit_rate (Optional[int], optional): The bit rate for mp3. Defaults to None.
            voice_experimental_controls_speed (Optional[str], optional): Speed control. Defaults to None.
            voice_experimental_controls_emotion (Optional[List[str]], optional): Emotion controls. Defaults to None.
            output_path (Optional[str], optional): Path to save the audio file. Defaults to None.
            save_to_file (bool, optional): Whether to save the audio to a file. Defaults to True.
            output_filename (Optional[str], optional): Specific filename to use when saving. Defaults to None (auto-generated).

        Returns:
            str: JSON string containing the result information.
        """
        try:
            # Normalize language code
            normalized_language = language.split("-")[0] if "-" in language else language

            # Ensure we have a valid voice ID *before* building params
            valid_voice_id = self._get_valid_voice_id(voice_id, normalized_language)
            logger.info(f"Using voice_id: {valid_voice_id} for infill operation.")
            logger.info(f"Using model_id: {model_id} for infill operation.")

            # Create proper output_format based on container type
            output_format: Dict[str, Any]
            requested_bit_rate = output_format_bit_rate or 128000  # Default to 128kbps if not provided

            if output_format_container == "mp3":
                # Cap MP3 bitrate at 192kbps
                capped_bit_rate = min(requested_bit_rate, 192000)
                if requested_bit_rate > 192000:
                    logger.warning(
                        f"Requested MP3 bit rate {requested_bit_rate} for infill exceeds supported limit. Capping at {capped_bit_rate}."
                    )

                output_format = {
                    "container": "mp3",
                    "sample_rate": output_format_sample_rate,
                    "bit_rate": capped_bit_rate,  # Use capped value
                    "encoding": output_format_encoding or "mp3",  # API requires encoding field even for mp3
                }
            elif output_format_container in ["wav", "raw"]:
                encoding = output_format_encoding or "pcm_s16le"  # Default encoding if not provided
                output_format = {
                    "container": output_format_container,
                    "sample_rate": output_format_sample_rate,
                    "encoding": encoding,
                }
            else:
                # Fallback for any other container
                output_format = {
                    "container": output_format_container,
                    "sample_rate": output_format_sample_rate,
                    "encoding": output_format_encoding or "pcm_s16le",  # Always provide an encoding
                }
                # Add bit_rate for formats that need it
                if output_format_bit_rate:
                    output_format["bit_rate"] = output_format_bit_rate

            # --- Prepare voice dictionary ---
            voice_dict: Dict[str, Any] = {"id": valid_voice_id}
            experimental_controls: Dict[str, Any] = {}
            if voice_experimental_controls_speed:
                experimental_controls["speed"] = voice_experimental_controls_speed
            if voice_experimental_controls_emotion:
                experimental_controls["emotion"] = voice_experimental_controls_emotion
            if experimental_controls:
                voice_dict["experimental_controls"] = experimental_controls

            # --- Prepare parameters for Cartesia SDK ---
            infill_params: Dict[str, Any] = {
                "model_id": model_id,
                "infill_transcript": transcript,
                "voice": voice_dict,  # Use the nested voice dictionary
                "language": normalized_language,
                "output_format": output_format,
            }

            # Read audio files if paths are provided
            prefix_audio_bytes = None
            if left_audio_path:
                try:
                    with open(left_audio_path, "rb") as f:
                        prefix_audio_bytes = f.read()
                    infill_params["prefix_audio"] = prefix_audio_bytes
                except FileNotFoundError:
                    logger.error(f"Left audio file not found: {left_audio_path}")
                    return json.dumps({"error": f"Left audio file not found: {left_audio_path}"})
                except Exception as e:
                    logger.error(f"Error reading left audio file {left_audio_path}: {e}")
                    return json.dumps({"error": f"Error reading left audio file: {e}"})

            suffix_audio_bytes = None
            if right_audio_path:
                try:
                    with open(right_audio_path, "rb") as f:
                        suffix_audio_bytes = f.read()
                    infill_params["suffix_audio"] = suffix_audio_bytes
                except FileNotFoundError:
                    logger.error(f"Right audio file not found: {right_audio_path}")
                    return json.dumps({"error": f"Right audio file not found: {right_audio_path}"})
                except Exception as e:
                    logger.error(f"Error reading right audio file {right_audio_path}: {e}")
                    return json.dumps({"error": f"Error reading right audio file: {e}"})

            # Log parameters just before the API call for debugging
            # Avoid logging full audio bytes
            log_params = {
                k: v if k not in ["prefix_audio", "suffix_audio"] else f"{len(v)} bytes" if v else None
                for k, v in infill_params.items()
            }
            logger.debug(f"Calling Cartesia tts.infill with params: {log_params}")

            # Make the API call for infill using the correct SDK method signature
            audio_data = self.client.tts.infill(**infill_params)

            total_bytes = len(audio_data)

            # Save to file if requested
            if output_path or save_to_file:
                file_path = None

                if output_path:
                    # Ensure output_path is treated as a relative path within output_dir
                    file_path = self.output_dir / Path(output_path).name
                else:
                    if not output_filename:
                        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                        output_filename = f"infill_{timestamp}.{output_format_container}"
                    file_path = self.output_dir / output_filename

                # Ensure the directory exists before writing
                file_path.parent.mkdir(parents=True, exist_ok=True)

                with open(file_path, "wb") as f:
                    f.write(audio_data)

                return json.dumps({"success": True, "file_path": str(file_path), "total_bytes": total_bytes}, indent=4)
            else:
                # Even when not saving to file, return a JSON string not binary data
                return json.dumps(
                    {"success": True, "total_bytes": total_bytes, "data": "Binary audio data (not displayed)"}, indent=4
                )

        except Exception as e:
            logger.error(f"Error generating infill audio with Cartesia: {e}", exc_info=True)
            return json.dumps({"error": str(e)})

    def get_api_status(self) -> str:
        """Get the status of the Cartesia API.

        Returns:
            str: JSON string containing the API status.
        """
        try:
            result = self.client.api_status.get()
            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error getting Cartesia API status: {e}")
            return json.dumps({"error": str(e)})

    def list_datasets(self) -> str:
        """List all available datasets in Cartesia.

        Returns:
            str: JSON string containing the available datasets.
        """
        try:
            result = self.client.datasets.list()
            # The SDK might return objects, ensure conversion if necessary
            # Assuming result is already list of dicts or similar JSON-serializable
            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error listing Cartesia datasets: {e}")
            return json.dumps({"error": str(e)})

    def create_dataset(
        self,
        name: str,
        description: Optional[str] = None,
        dataset_file: Optional[IO[bytes]] = None,  # Accept file handle
    ) -> str:
        """Create a new dataset in Cartesia, optionally uploading a file.

        Args:
            name (str): The name for the new dataset.
            description (Optional[str]): Description for the dataset.
            dataset_file (Optional[IO[bytes]]): File handle for the dataset CSV/TSV.

        Returns:
            str: JSON string containing the created dataset information.
        """
        try:
            params: Dict[str, Any] = {"name": name}
            if description:
                params["description"] = description
            if dataset_file:
                params["file"] = dataset_file  # Pass the file handle

            result = self.client.datasets.create(**params)
            # Assuming result is JSON-serializable
            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error creating Cartesia dataset: {e}")
            return json.dumps({"error": str(e)})

    def get_dataset(self, dataset_id: str) -> str:
        """Get information about a specific dataset.

        Args:
            dataset_id (str): The ID of the dataset to retrieve.

        Returns:
            str: JSON string containing the dataset information.
        """
        try:
            result = self.client.datasets.get(id=dataset_id)
            # Assuming result is JSON-serializable
            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error getting Cartesia dataset: {e}")
            return json.dumps({"error": str(e)})

    def update_dataset(self, dataset_id: str, name: Optional[str] = None, description: Optional[str] = None) -> str:
        """Update information for a specific dataset.

        Args:
            dataset_id (str): The ID of the dataset to update.
            name (Optional[str]): The new name for the dataset.
            description (Optional[str]): The new description for the dataset.

        Returns:
            str: JSON string containing the updated dataset information.
        """
        try:
            params: Dict[str, Any] = {"id": dataset_id}
            if name is not None:
                params["name"] = name
            if description is not None:
                params["description"] = description

            if len(params) == 1:  # Only id was provided
                return json.dumps({"error": "No update parameters (name or description) provided."})

            result = self.client.datasets.update(**params)
            # Assuming result is JSON-serializable
            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error updating Cartesia dataset: {e}")
            return json.dumps({"error": str(e)})

    def delete_dataset(self, dataset_id: str) -> str:
        """Delete a specific dataset.

        Args:
            dataset_id (str): The ID of the dataset to delete.

        Returns:
            str: JSON string confirming the deletion or reporting an error.
        """
        try:
            result = self.client.datasets.delete(id=dataset_id)
            # Assuming result is JSON-serializable (e.g., {"message": "..."})
            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error deleting Cartesia dataset: {e}")
            return json.dumps({"error": str(e)})

    def list_dataset_files(self, dataset_id: str) -> str:
        """List all files in a Cartesia dataset.

        Args:
            dataset_id (str): The ID of the dataset.

        Returns:
            str: JSON string containing the dataset files.
        """
        try:
            result = self.client.datasets.list_files(id=dataset_id)
            # Assuming result is JSON-serializable
            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error listing files in Cartesia dataset: {e}")
            return json.dumps({"error": str(e)})

    def save_audio_to_file(self, audio_data: bytes, filename: str, directory: Optional[str] = None) -> str:
        """Save audio data to a file.

        Args:
            audio_data (bytes): The audio data bytes to save.
            filename (str): The filename to save to (without path).
            directory (Optional[str], optional): The directory to save to. Defaults to self.output_dir.

        Returns:
            str: JSON string containing the result information.
        """
        try:
            save_dir = Path(directory) if directory else self.output_dir
            file_path = save_dir / filename

            with open(file_path, "wb") as f:
                f.write(audio_data)

            return json.dumps({"success": True, "file_path": str(file_path), "size_bytes": len(audio_data)}, indent=4)
        except Exception as e:
            logger.error(f"Error saving audio data: {e}")
            return json.dumps({"error": str(e)})

    def text_to_speech_stream(
        self,
        transcript: str,
        model_id: str = "sonic-2",
        voice_id: Optional[str] = None,
        language: str = "en",
        output_format_container: str = "mp3",
        output_format_sample_rate: int = 44100,
        output_format_bit_rate: int = 128000,
        output_format_encoding: Optional[str] = None,
        duration: Optional[float] = None,
        voice_experimental_controls_speed: Optional[str] = None,
        voice_experimental_controls_emotion: Optional[List[str]] = None,
    ) -> str:
        """
        Stream text to speech using the Cartesia API.

        Args:
            transcript: The text to convert to speech
            model_id: The ID of the TTS model to use. Defaults to "sonic-2".
            voice_id: The ID of the voice to use
            language: The language code (e.g., "en" for English)
            output_format_container: The format container ("mp3", "wav", "raw")
            output_format_sample_rate: The sample rate (e.g., 44100)
            output_format_bit_rate: The bit rate for MP3 formats (e.g., 128000)
            output_format_encoding: The encoding format
            duration (Optional[float], optional): The duration of the audio. Defaults to None.
            voice_experimental_controls_speed (Optional[str], optional): Speed control. Defaults to None.
            voice_experimental_controls_emotion (Optional[List[str]], optional): Emotion controls. Defaults to None.

        Returns:
            str: JSON string containing the result information
        """
        try:
            # Normalize language code
            normalized_language = language.split("-")[0] if "-" in language else language

            # Ensure we have a valid voice ID *before* building params
            valid_voice_id = self._get_valid_voice_id(voice_id, normalized_language)
            logger.info(f"Using voice_id: {valid_voice_id} for text_to_speech_stream.")
            logger.info(f"Using model_id: {model_id} for text_to_speech_stream.")  # Log model ID

            # Create proper output_format based on container type
            output_format: Dict[str, Any]
            if output_format_container == "mp3":
                output_format = {
                    "container": "mp3",
                    "sample_rate": output_format_sample_rate,
                    "bit_rate": output_format_bit_rate or 128000,
                    "encoding": output_format_encoding or "mp3",
                }
            elif output_format_container in ["wav", "raw"]:
                encoding = output_format_encoding or "pcm_s16le"
                output_format = {
                    "container": output_format_container,
                    "sample_rate": output_format_sample_rate,
                    "encoding": encoding,
                }
            else:
                output_format = {
                    "container": output_format_container,
                    "sample_rate": output_format_sample_rate,
                    "encoding": output_format_encoding or "pcm_s16le",
                }
                if output_format_bit_rate:
                    output_format["bit_rate"] = output_format_bit_rate

            # Base parameters for the API call
            params: Dict[str, Any] = {
                "model_id": model_id,
                "transcript": transcript,
                "voice": {"mode": "id", "id": valid_voice_id},
                "language": normalized_language,
                "output_format": output_format,
            }

            # Add optional duration parameter if provided
            if duration is not None:
                params["duration"] = duration

            # Add experimental controls if provided
            if voice_experimental_controls_speed or voice_experimental_controls_emotion:
                voice_controls: Dict[str, Any] = {}
                if voice_experimental_controls_speed:
                    voice_controls["speed"] = voice_experimental_controls_speed
                if voice_experimental_controls_emotion:
                    voice_controls["emotion"] = voice_experimental_controls_emotion
                params["voice_experimental_controls"] = voice_controls

            # Log parameters just before the API call for debugging
            logger.debug(f"Calling Cartesia tts.sse with params: {params}")

            # Make the streaming API call using .sse()
            sse_iterator = self.client.tts.sse(**params)

            # Consume the iterator (or handle the stream as needed)
            # In a real streaming scenario, you'd process each event in the sse_iterator
            # For now, just iterating through it to ensure the call works and logging completion.
            logger.info("SSE stream initiated. Consuming stream...")
            for event in sse_iterator:
                # Log event type or data for debugging if necessary
                logger.debug(f"Received SSE event: type={type(event)}")
                # Example: Check event type and extract data if needed
                # if isinstance(event, SomeExpectedEventType):
                #    process_event(event)
                pass  # Replace with actual stream processing logic if required by the caller
            logger.info("SSE stream consumed/finished.")

            # Note: Returning the raw stream response might not be ideal for the agent framework
            # which expects JSON strings. Consider how the agent will handle this stream.
            # For now, returning a success message indicating a stream was initiated.
            # The actual stream handling would likely happen outside this tool method.
            return json.dumps({"success": True, "message": "Streaming finished."}, indent=4)
            # Or potentially: return {"success": True, "stream": response} # If framework handles non-JSON

        except AttributeError as ae:
            # Catch potential attribute errors related to changed client structure
            logger.error(f"AttributeError during streaming: {ae}. Check SDK v2 method names.", exc_info=True)
            return json.dumps(
                {
                    "error": f"AttributeError: {ae}. Check SDK v2 compatibility.",
                    "detail": "Likely due to using an old method name like .stream instead of .sse",
                }
            )
        except Exception as e:
            logger.error(f"Error streaming speech with Cartesia: {e}", exc_info=True)
            return json.dumps({"error": str(e)})

    def batch_text_to_speech(
        self,
        transcripts: List[str],
        model_id: str = "sonic-2",
        voice_id: Optional[str] = None,
        language: str = "en",
        output_format_container: str = "mp3",
        output_format_sample_rate: int = 44100,
        output_format_bit_rate: int = 128000,
        output_format_encoding: Optional[str] = None,
        output_dir: Optional[str] = None,
        duration: Optional[float] = None,
        voice_experimental_controls_speed: Optional[str] = None,
        voice_experimental_controls_emotion: Optional[List[str]] = None,
    ) -> str:  # Return type changed to str to match others
        """
        Convert multiple texts to speech using the Cartesia API.

        Args:
            transcripts: List of texts to convert to speech
            model_id: The ID of the TTS model to use. Defaults to "sonic-2".
            voice_id: The ID of the voice to use
            language: The language code (e.g., "en" for English)
            output_format_container: The format container ("mp3", "wav", "raw")
            output_format_sample_rate: The sample rate (e.g., 44100)
            output_format_bit_rate: The bit rate for MP3 formats (e.g., 128000)
            output_format_encoding: The encoding format
            output_dir: Directory to save the audio files (default: self.output_dir)
            duration (Optional[float], optional): The duration for each audio file. Defaults to None.
            voice_experimental_controls_speed (Optional[str], optional): Speed control for each audio file. Defaults to None.
            voice_experimental_controls_emotion (Optional[List[str]], optional): Emotion controls for each audio file. Defaults to None.

        Returns:
            str: JSON string summarizing the batch operation results.
        """
        try:
            # Normalize language code - API expects "en" not "en-US"
            normalized_language = language.split("-")[0] if "-" in language else language

            # Ensure we have a valid voice ID *before* the loop
            valid_voice_id = self._get_valid_voice_id(voice_id, normalized_language)
            logger.info(f"Using voice_id: {valid_voice_id} for batch operation.")
            logger.info(f"Using model_id: {model_id} for batch operation.")  # Log the model ID

            save_dir = Path(output_dir) if output_dir else self.output_dir
            results: List[Optional[str]] = []

            # Prepare voice controls once if they are consistent for the batch
            voice_controls: Dict[str, Any] = {}
            if voice_experimental_controls_speed:
                voice_controls["speed"] = voice_experimental_controls_speed
            if voice_experimental_controls_emotion:
                voice_controls["emotion"] = voice_experimental_controls_emotion

            for i, text in enumerate(transcripts):
                try:
                    # Create proper output_format based on container type
                    output_format: Dict[str, Any]
                    requested_bit_rate = output_format_bit_rate or 128000  # Use provided or default for batch item

                    if output_format_container == "mp3":
                        # Cap MP3 bitrate at 192kbps
                        capped_bit_rate = min(requested_bit_rate, 192000)
                        if requested_bit_rate > 192000:
                            logger.warning(
                                f"Requested MP3 bit rate {requested_bit_rate} for batch item {i + 1} exceeds supported limit. Capping at {capped_bit_rate}."
                            )

                        output_format = {
                            "container": "mp3",
                            "sample_rate": output_format_sample_rate,
                            "bit_rate": capped_bit_rate,  # Use capped value
                            "encoding": output_format_encoding or "mp3",
                        }
                    elif output_format_container in ["wav", "raw"]:
                        encoding = output_format_encoding or "pcm_s16le"
                        output_format = {
                            "container": output_format_container,
                            "sample_rate": output_format_sample_rate,
                            "encoding": encoding,
                        }
                    else:
                        output_format = {
                            "container": output_format_container,
                            "sample_rate": output_format_sample_rate,
                            "encoding": output_format_encoding or "pcm_s16le",
                        }
                        if requested_bit_rate:
                            output_format["bit_rate"] = requested_bit_rate

                    # Create the parameters object exactly as required by the SDK v2
                    params: Dict[str, Any] = {
                        "model_id": model_id,
                        "transcript": text,
                        # Pass voice as a dict { "mode": "id", "id": ... }
                        "voice": {"mode": "id", "id": valid_voice_id},
                        "language": normalized_language,  # Ensure language code is supported
                        "output_format": output_format,
                    }

                    # Add optional duration if provided
                    if duration is not None:
                        params["duration"] = duration

                    # Add voice controls if they exist (Check v2 compatibility)
                    # if voice_controls:
                    #     params["voice_experimental_controls"] = voice_controls
                    if voice_controls:
                        logger.warning(
                            "Passing voice_experimental_controls might not be supported or changed in Cartesia v2 batch. Ignoring for now."
                        )

                    # Log parameters just before the API call for debugging
                    logger.debug(f"Calling Cartesia tts.bytes with params (item {i + 1}): {params}")

                    # Make the API call - v2 returns an iterator
                    audio_iterator = self.client.tts.bytes(**params)
                    # Concatenate bytes
                    audio_data = b"".join(chunk for chunk in audio_iterator)

                    # Create filename
                    filename = f"batch_tts_{i + 1}.{output_format_container}"
                    file_path = save_dir / filename

                    # Ensure directory exists
                    file_path.parent.mkdir(parents=True, exist_ok=True)

                    # Save the file
                    with open(file_path, "wb") as f:
                        f.write(audio_data)

                    results.append(str(file_path))

                except Exception as e:
                    # Log the specific error for this item, but continue the batch
                    logger.error(f"Error processing text {i + 1} in batch: {e}", exc_info=True)
                    results.append(None)  # Keep track that an error occurred for this item

            # Filter out None values before summarizing
            successful_results = [r for r in results if r]
            error_count = len(results) - len(successful_results)

            return json.dumps(
                {
                    "success": True,
                    "total": len(transcripts),
                    "success_count": len(successful_results),
                    "error_count": error_count,
                    "output_directory": str(save_dir),
                    "details": successful_results,
                },
                indent=4,
            )

        except Exception as e:
            # Log error for the entire batch operation setup (e.g., getting voice ID failed)
            logger.error(f"Error in batch text-to-speech setup: {e}", exc_info=True)
            return json.dumps({"error": str(e)})
