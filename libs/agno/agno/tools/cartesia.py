import json
from os import getenv
from typing import Dict, List, Optional, Any

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
        list_voices_enabled: bool = True,
        voice_get_enabled: bool = True,
        voice_clone_enabled: bool = False,
        voice_delete_enabled: bool = False,
        voice_update_enabled: bool = False,
        voice_localize_enabled: bool = False,
        voice_mix_enabled: bool = False,
        voice_create_enabled: bool = False,
        voice_changer_enabled: bool = False,
        infill_enabled: bool = False,
        api_status_enabled: bool = False,
        datasets_enabled: bool = False,
    ):
        super().__init__(name="cartesia_tools")

        self.api_key = api_key or getenv("CARTESIA_API_KEY")

        if not self.api_key:
            raise ValueError("`api_key` is required")

        self.client = Cartesia(api_key=self.api_key)

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

    def clone_voice(
        self,
        name: str,
        audio_file_path: str,
        description: Optional[str] = None,
        language: Optional[str] = None,
        mode: str = "stability",
        enhance: bool = False,
        transcript: Optional[str] = None
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
                params = {
                    "name": name,
                    "clip": file,
                    "mode": mode,
                    "enhance": enhance
                }

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

    def update_voice(
        self,
        voice_id: str,
        name: str,
        description: str
    ) -> str:
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
                filtered_voice = {
                    "id": voice.get("id"),
                    "description": voice.get("description")
                }
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
        dialect: Optional[str] = None
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
                "original_speaker_gender": original_speaker_gender
            }

            if dialect:
                params["dialect"] = dialect

            result = self.client.voices.localize(**params)
            return json.dumps(result, indent=4)
        except Exception as e:
            logger.error(f"Error localizing voice with Cartesia: {e}")
            return json.dumps({"error": str(e)})

    def mix_voices(
        self,
        voices: List[Dict[str, Any]]
    ) -> str:
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
        base_voice_id: Optional[str] = None
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
            params = {
                "name": name,
                "description": description,
                "embedding": embedding
            }

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
        output_format_bit_rate: Optional[int] = None
    ) -> str:
        """Change the voice in an audio file.

        Args:
            audio_file_path (str): Path to the audio file to change.
            voice_id (str): The ID of the target voice.
            output_format_container (str): The format container for the output audio.
            output_format_sample_rate (int): The sample rate for the output audio.
            output_format_encoding (Optional[str], optional): The encoding for raw/wav containers. Defaults to None.
            output_format_bit_rate (Optional[int], optional): The bit rate for mp3 containers. Defaults to None.

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
                    "output_format_sample_rate": output_format_sample_rate
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
        model_id: str,
        transcript: str,
        voice_id: str,
        language: str,
        output_format_container: str = "mp3",
        output_format_sample_rate: int = 44100,
        output_format_encoding: Optional[str] = None,
        output_format_bit_rate: Optional[int] = None,
        duration: Optional[float] = None
    ) -> str:
        """Generate speech from text.

        Args:
            model_id (str): The ID of the model to use.
            transcript (str): The text to convert to speech.
            voice_id (str): The ID of the voice to use.
            language (str): The language code.
            output_format_container (str): The format container for the output audio.
            output_format_sample_rate (int): The sample rate for the output audio.
            output_format_encoding (Optional[str], optional): The encoding for raw/wav containers. Defaults to None.
            output_format_bit_rate (Optional[int], optional): The bit rate for mp3 containers. Defaults to None.
            duration (Optional[float], optional): The maximum duration in seconds. Defaults to None.

        Returns:
            str: JSON string containing the result information.
        """
        logger.info(f"Generating speech for text: {transcript[:50]}...")
        try:
            voice = {"mode": "id", "id": voice_id}
            output_format = {
                "container": output_format_container,
                "sample_rate": output_format_sample_rate
            }

            if output_format_encoding:
                output_format["encoding"] = output_format_encoding

            if output_format_bit_rate:
                output_format["bit_rate"] = output_format_bit_rate

            params = {
                "model_id": model_id,
                "transcript": transcript,
                "voice": voice,
                "language": language,
                "output_format": output_format
            }

            if duration:
                params["duration"] = duration

            result = self.client.tts.bytes(**params)
            return json.dumps({"success": True, "result": str(result)[:100] + "..."}, indent=4)
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
        voice_experimental_controls_emotion: Optional[List[str]] = None
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
                "output_format_sample_rate": output_format_sample_rate
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
