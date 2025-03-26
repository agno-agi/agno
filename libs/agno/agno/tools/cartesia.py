import datetime
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from cartesia import Cartesia
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

        self.api_key = api_key or os.getenv("CARTESIA_API_KEY")

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
            self.register(self.list_dataset_files)
        if list_voices_enabled:
            self.register(self.list_voices)
        if save_audio_enabled:
            self.register(self.save_audio_to_file)
        if batch_processing_enabled:
            self.register(self.batch_text_to_speech)

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
        logger.info(f"Cloning voice from audio file: {audio_file_path}")
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
        logger.info(f"Deleting voice: {voice_id}")
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
        logger.info(f"Updating voice: {voice_id}")
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
        logger.info(f"Getting voice information: {voice_id}")
        try:
            result = self.client.voices.get(id=voice_id)
            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error getting voice information from Cartesia: {e}")
            return json.dumps({"error": str(e)})

    def list_voices(self) -> str:
        """List all available voices in Cartesia.

        Returns:
            str: JSON string containing the list of available voices.
        """
        logger.info("Listing available Cartesia voices")
        try:
            result = self.client.voices.list()
            # Filter to only include id and description for each voice
            filtered_result = []
            for voice in result:
                filtered_voice = {"id": voice.get("id"), "description": voice.get("description")}
                filtered_result.append(filtered_voice)
            return json.dumps(filtered_result, indent=4)
        except Exception as e:
            logger.error(f"Error listing voices from Cartesia: {e}")
            return json.dumps({"error": str(e)})

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
        logger.info(f"Localizing voice {voice_id} to language {language}")
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
        logger.info(f"Mixing {len(voices)} voices")
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
        logger.info(f"Creating voice: {name}")
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
        logger.info(f"Changing voice in audio file: {audio_file_path}")
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
        model_id: str = None,  # Allow any model ID (sonic-2, sonic-turbo, etc.)
        voice_id: str = None,
        language: str = "en",
        output_format_container: str = "mp3",
        output_format_sample_rate: int = 44100,
        output_format_bit_rate: int = 128000,
        output_format_encoding: str = None,
        output_path: str = None,
        **kwargs,
    ) -> str:  # Always return a string for agent framework
        """
        Convert text to speech using the Cartesia API.

        Args:
            transcript: The text to convert to speech
            model_id: The ID of the TTS model to use (e.g., "sonic-2", "sonic-turbo")
            voice_id: The ID of the voice to use
            language: The language code (e.g., "en" for English)
            output_format_container: The format container ("mp3", "wav", "raw")
            output_format_sample_rate: The sample rate (e.g., 44100)
            output_format_bit_rate: The bit rate for MP3 formats (e.g., 128000)
            output_format_encoding: The encoding format (e.g., "mp3" for MP3, "pcm_s16le" for WAV)
            output_path: The path to save the audio file (default: None - saves to default location)
            **kwargs: Additional parameters to pass to the API

        Returns:
            str: JSON string containing the result information
        """
        logger.info(f"Generating speech for: {transcript[:50]}...")
        try:
            # Normalize language code - API expects "en" not "en-US"
            normalized_language = language.split("-")[0] if "-" in language else language
            logger.info(f"Normalized language from {language} to {normalized_language}")

            # Create proper output_format based on container type
            if output_format_container == "mp3":
                output_format = {
                    "container": "mp3",
                    "sample_rate": output_format_sample_rate,
                    "bit_rate": output_format_bit_rate or 128000,  # Default to 128kbps if not provided
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

            # Create the parameters object exactly as required by the SDK
            params = {
                "model_id": model_id,
                "transcript": transcript,
                "voice_id": voice_id,
                "language": normalized_language,
                "output_format": output_format,
            }

            # Log the API call for debugging
            logger.info(f"Calling TTS API with params: {json.dumps(params)}")

            # Make the API call
            audio_data = self.client.tts.bytes(**params)

            total_bytes = len(audio_data)
            logger.info(f"TTS API returned {total_bytes} bytes")

            # Save to file if requested
            if output_path or kwargs.get("save_to_file", True):  # Default to saving the file
                file_path = None

                if output_path:
                    file_path = self.output_dir / output_path
                else:
                    # For backward compatibility
                    output_filename = kwargs.get("output_filename")
                    if not output_filename:
                        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                        output_filename = f"tts_{timestamp}.{output_format_container}"

                    file_path = self.output_dir / output_filename

                with open(file_path, "wb") as f:
                    f.write(audio_data)

                logger.info(f"Generated {total_bytes} bytes of audio, saved to {file_path}")

                return json.dumps({"success": True, "file_path": str(file_path), "total_bytes": total_bytes}, indent=4)
            else:
                # Even when not saving to file, return a JSON string not binary data
                return json.dumps(
                    {"success": True, "total_bytes": total_bytes, "data": "Binary audio data (not displayed)"}, indent=4
                )

        except Exception as e:
            logger.error(f"Error generating speech with Cartesia: {e}")
            return json.dumps({"error": str(e)})

    def infill_audio(
        self,
        transcript: str,
        voice_id: str,
        model_id: str,
        language: str,
        left_audio_path: Optional[str] = None,
        right_audio_path: Optional[str] = None,
        output_format_container: str = "wav",
        output_format_sample_rate: int = 44100,
        output_format_encoding: Optional[str] = None,
        output_format_bit_rate: Optional[int] = None,
        voice_experimental_controls_speed: Optional[str] = None,
        voice_experimental_controls_emotion: Optional[List[str]] = None,
    ) -> str:
        """Generate audio that smoothly connects two existing audio segments.

        Args:
            transcript (str): The infill text to generate.
            voice_id (str): The ID of the voice to use.
            model_id (str): The ID of the model to use.
            language (str): The language code.
            left_audio_path (Optional[str], optional): Path to the left audio file. Defaults to None.
            right_audio_path (Optional[str], optional): Path to the right audio file. Defaults to None.
            output_format_container (str, optional): The format container. Defaults to "wav".
            output_format_sample_rate (int, optional): The sample rate. Defaults to 44100.
            output_format_encoding (Optional[str], optional): The encoding for raw/wav. Defaults to None.
            output_format_bit_rate (Optional[int], optional): The bit rate for mp3. Defaults to None.
            voice_experimental_controls_speed (Optional[str], optional): Speed control. Defaults to None.
            voice_experimental_controls_emotion (Optional[List[str]], optional): Emotion controls. Defaults to None.

        Returns:
            str: JSON string containing the result information.
        """
        logger.info(f"Generating infill audio for text: {transcript[:50]}...")
        try:
            params = {
                "model_id": model_id,
                "language": language,
                "transcript": transcript,
                "voice_id": voice_id,
                "output_format_container": output_format_container,
                "output_format_sample_rate": output_format_sample_rate,
            }

            if output_format_encoding:
                params["output_format_encoding"] = output_format_encoding

            if output_format_bit_rate:
                params["output_format_bit_rate"] = output_format_bit_rate

            if voice_experimental_controls_speed:
                params["voice_experimental_controls_speed"] = voice_experimental_controls_speed

            if voice_experimental_controls_emotion:
                params["voice_experimental_controls_emotion"] = voice_experimental_controls_emotion

            if left_audio_path:
                with open(left_audio_path, "rb") as file:
                    params["left_audio"] = file

            if right_audio_path:
                with open(right_audio_path, "rb") as file:
                    params["right_audio"] = file

            result = self.client.infill.bytes(**params)
            return json.dumps({"success": True, "result": str(result)[:100] + "..."}, indent=4)
        except Exception as e:
            logger.error(f"Error generating infill audio with Cartesia: {e}")
            return json.dumps({"error": str(e)})

    def get_api_status(self) -> str:
        """Get the status of the Cartesia API.

        Returns:
            str: JSON string containing the API status.
        """
        logger.info("Getting Cartesia API status")
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
        logger.info("Listing available Cartesia datasets")
        try:
            result = self.client.datasets.list()
            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error listing Cartesia datasets: {e}")
            return json.dumps({"error": str(e)})

    def create_dataset(self, name: str) -> str:
        """Create a new dataset in Cartesia.

        Args:
            name (str): The name for the new dataset.

        Returns:
            str: JSON string containing the created dataset information.
        """
        logger.info(f"Creating Cartesia dataset: {name}")
        try:
            result = self.client.datasets.create(name=name)
            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error creating Cartesia dataset: {e}")
            return json.dumps({"error": str(e)})

    def list_dataset_files(self, dataset_id: str) -> str:
        """List all files in a Cartesia dataset.

        Args:
            dataset_id (str): The ID of the dataset.

        Returns:
            str: JSON string containing the dataset files.
        """
        logger.info(f"Listing files in Cartesia dataset: {dataset_id}")
        try:
            result = self.client.datasets.list_files(id=dataset_id)
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
        logger.info(f"Saving audio data to file: {filename}")
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
        model_id: str = None,  # Allow any model ID
        voice_id: str = None,
        language: str = "en",
        output_format_container: str = "mp3",
        output_format_sample_rate: int = 44100,
        output_format_bit_rate: int = 128000,
        output_format_encoding: str = None,
        **kwargs,
    ) -> str:  # Always return a string for agent framework
        """
        Stream text to speech using the Cartesia API.

        Args:
            transcript: The text to convert to speech
            model_id: The ID of the TTS model to use (e.g., "sonic-2", "sonic-turbo")
            voice_id: The ID of the voice to use
            language: The language code (e.g., "en" for English)
            output_format_container: The format container ("mp3", "wav", "raw")
            output_format_sample_rate: The sample rate (e.g., 44100)
            output_format_bit_rate: The bit rate for MP3 formats (e.g., 128000)
            output_format_encoding: The encoding format
            **kwargs: Additional parameters to pass to the API

        Returns:
            str: JSON string containing the result information
        """
        logger.info(f"Streaming speech for text: {transcript[:50]}...")
        try:
            # Normalize language code - API expects "en" not "en-US"
            normalized_language = language.split("-")[0] if "-" in language else language
            logger.info(f"Normalized language from {language} to {normalized_language}")

            # Create proper output_format based on container type
            if output_format_container == "mp3":
                output_format = {
                    "container": "mp3",
                    "sample_rate": output_format_sample_rate,
                    "bit_rate": output_format_bit_rate or 128000,  # Default to 128kbps if not provided
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

            # Create the parameters object exactly as required by the SDK
            params = {
                "model_id": model_id,
                "transcript": transcript,
                "voice_id": voice_id,
                "language": normalized_language,
                "output_format": output_format,
            }

            # Log the API call for debugging
            logger.info(f"Calling TTS API with params: {json.dumps(params)}")

            # Use the bytes method since we're not actually streaming
            audio_data = self.client.tts.bytes(**params)

            total_bytes = len(audio_data)
            logger.info(f"TTS API returned {total_bytes} bytes")

            # Save to file (default behavior for agent framework)
            save_to_file = kwargs.get("save_to_file", True)
            if save_to_file:
                output_filename = kwargs.get("output_filename")
                if not output_filename:
                    # Create a filename based on first few words of transcript
                    words = transcript.split()[:3]
                    filename_base = "_".join(words).lower().replace(" ", "_")
                    filename_base = "".join(c for c in filename_base if c.isalnum() or c == "_")
                    output_filename = f"{filename_base}.{output_format_container}"

                file_path = self.output_dir / output_filename
                with open(file_path, "wb") as f:
                    f.write(audio_data)

                return json.dumps(
                    {
                        "success": True,
                        "streaming": False,  # We're using bytes method, not streaming
                        "total_bytes": total_bytes,
                        "file_path": str(file_path),
                    },
                    indent=4,
                )
            else:
                # Even when not saving to file, return JSON string not binary data
                return json.dumps(
                    {
                        "success": True,
                        "streaming": False,
                        "total_bytes": total_bytes,
                        "data": "Binary audio data (not displayed)",
                    },
                    indent=4,
                )

        except Exception as e:
            logger.error(f"Error streaming speech with Cartesia: {e}")
            return json.dumps({"error": str(e)})

    def batch_text_to_speech(
        self,
        transcripts: List[str],
        model_id: str = None,  # Allow any model ID
        voice_id: str = None,
        language: str = "en",
        output_format_container: str = "mp3",
        output_format_sample_rate: int = 44100,
        output_format_bit_rate: int = 128000,
        output_format_encoding: str = None,
        output_dir: str = None,
        **kwargs,
    ) -> List[str]:
        """
        Convert multiple texts to speech using the Cartesia API.

        Args:
            transcripts: List of texts to convert to speech
            model_id: The ID of the TTS model to use (e.g., "sonic-2", "sonic-turbo")
            voice_id: The ID of the voice to use
            language: The language code (e.g., "en" for English)
            output_format_container: The format container ("mp3", "wav", "raw")
            output_format_sample_rate: The sample rate (e.g., 44100)
            output_format_bit_rate: The bit rate for MP3 formats (e.g., 128000)
            output_format_encoding: The encoding format
            output_dir: Directory to save the audio files (default: self.output_dir)
            **kwargs: Additional parameters to pass to the API

        Returns:
            List[str]: List of paths to the saved audio files
        """
        logger.info(f"Batch processing {len(transcripts)} texts to speech")
        try:
            # Normalize language code - API expects "en" not "en-US"
            normalized_language = language.split("-")[0] if "-" in language else language
            logger.info(f"Normalized language from {language} to {normalized_language}")

            save_dir = Path(output_dir) if output_dir else self.output_dir
            results = []

            for i, text in enumerate(transcripts):
                try:
                    # Create proper output_format based on container type
                    if output_format_container == "mp3":
                        output_format = {
                            "container": "mp3",
                            "sample_rate": output_format_sample_rate,
                            "bit_rate": output_format_bit_rate or 128000,  # Default to 128kbps if not provided
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

                    # Create the parameters object exactly as required by the SDK
                    params = {
                        "model_id": model_id,
                        "transcript": text,
                        "voice_id": voice_id,
                        "language": normalized_language,
                        "output_format": output_format,
                    }

                    # Log the API call for debugging
                    logger.info(f"Calling TTS API with params for text {i + 1}: {json.dumps(params)}")

                    # Make the API call
                    audio_data = self.client.tts.bytes(**params)

                    # Create filename
                    filename = f"batch_tts_{i + 1}.{output_format_container}"
                    file_path = save_dir / filename

                    # Save the file
                    with open(file_path, "wb") as f:
                        f.write(audio_data)

                    results.append(str(file_path))

                except Exception as e:
                    logger.error(f"Error processing text {i + 1}: {e}")
                    results.append(None)

            # Filter out None values
            results = [r for r in results if r]

            # Summarize results
            success_count = len(results)
            error_count = 0

            return json.dumps(
                {
                    "success": True,
                    "total": len(transcripts),
                    "success_count": success_count,
                    "error_count": error_count,
                    "output_directory": str(save_dir),
                    "details": results,
                },
                indent=4,
            )

        except Exception as e:
            logger.error(f"Error in batch text-to-speech processing: {e}")
            return json.dumps({"error": str(e)})
