from base64 import b64encode
from io import BytesIO
from os import getenv, path
from pathlib import Path
from typing import Literal, Optional
from uuid import uuid4

from agno.agent import Agent
from agno.media import AudioArtifact
from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from smallest import Smallest  # type: ignore
except ImportError:
    raise ImportError("SmallestAITools require 'smallestai' package. Run  `pip install smallestai` to install it.")

SmallestAIModel = Literal["lightning", "lightning-large"]


class ValidationError(Exception):
    """Exception raised for validation errors in SmallestAI parameters."""

    pass


class SmallestAITools(Toolkit):
    def __init__(
        self,
        voice_id: str = "emily",
        api_key: Optional[str] = None,
        target_directory: Optional[str] = None,
        model: SmallestAIModel = "lightning",
        sample_rate: int = 24000,
        speed: float = 1.0,
        consistency: float = 0.5,
        similarity: float = 0.0,
        enhancement: int = 0,
        add_wav_header: bool = True,
    ):
        super().__init__(name="smallest_ai_tools")

        self.api_key = api_key or getenv("SMALLEST_API_KEY")
        if not self.api_key:
            logger.error("SMALLEST_API_KEY not set. Please set the SMALLEST_API_KEY environment variable.")

        # Validate inputs
        self._validate_input(
            prompt="dummy text",  # Just for initialization validation
            model=str(model),
            sample_rate=int(sample_rate),
            speed=float(speed),
            consistency=float(consistency),
            similarity=float(similarity),
            enhancement=int(enhancement),
        )

        self.target_directory = target_directory
        self.voice_id = voice_id
        self.model = model
        self.sample_rate = sample_rate
        self.speed = speed
        self.consistency = consistency
        self.similarity = similarity
        self.enhancement = enhancement
        self.add_wav_header = add_wav_header

        if self.target_directory:
            target_path = Path(self.target_directory)
            target_path.mkdir(parents=True, exist_ok=True)

        self.smallest_client = Smallest(
            api_key=self.api_key,
            model=self.model,
            voice_id=self.voice_id,
            sample_rate=self.sample_rate,
            speed=self.speed,
            consistency=self.consistency,
            similarity=self.similarity,
            enhancement=self.enhancement,
            add_wav_header=self.add_wav_header,
        )

        self.register(self.get_voices)
        self.register(self.get_languages)
        self.register(self.get_models)
        self.register(self.add_voice)
        self.register(self.text_to_speech)

    def _validate_input(
        self,
        prompt: str,
        model: str,
        sample_rate: int,
        speed: float,
        consistency: Optional[float] = None,
        similarity: Optional[float] = None,
        enhancement: Optional[int] = None,
    ):
        """
        Validate input parameters for SmallestAI TTS.

        Args:
            prompt (str): Text to synthesize.
            model (str): TTS model.
            sample_rate (int): Audio sample rate.
            speed (float): Speech speed multiplier.
            consistency (Optional[float]): Word repetition and skipping control.
            similarity (Optional[float]): Similarity to reference control.
            enhancement (Optional[int]): Speech enhancement level.

        Raises:
            ValidationError: If any parameter is invalid.
        """
        if not prompt:
            raise ValidationError("Prompt cannot be empty.")

        if model not in ["lightning", "lightning-large"]:
            raise ValidationError(f"Invalid model: {model}. Must be one of ['lightning', 'lightning-large']")

        if not 8000 <= sample_rate <= 24000:
            raise ValidationError(f"Invalid sample rate: {sample_rate}. Must be between 8000 and 24000")

        if not 0.5 <= speed <= 2.0:
            raise ValidationError(f"Invalid speed: {speed}. Must be between 0.5 and 2.0")

        if consistency is not None and not 0.0 <= consistency <= 1.0:
            raise ValidationError(f"Invalid consistency: {consistency}. Must be between 0.0 and 1.0")

        if similarity is not None and not 0.0 <= similarity <= 1.0:
            raise ValidationError(f"Invalid similarity: {similarity}. Must be between 0.0 and 1.0")

        if enhancement is not None and not 0 <= enhancement <= 2:
            raise ValidationError(f"Invalid enhancement: {enhancement}. Must be between 0 and 2.")

    def _process_audio(self, audio_bytes: bytes) -> str:
        # Create a BytesIO object to handle the audio data
        audio_io = BytesIO(audio_bytes)
        audio_io.seek(0)  # Rewind the stream

        # Encode as Base64
        base64_audio = b64encode(audio_io.read()).decode("utf-8")

        # Optionally save to disk if target_directory exists
        if self.target_directory:
            extension = "wav"
            output_filename = f"{uuid4()}.{extension}"
            output_path = path.join(self.target_directory, output_filename)

            # Write from BytesIO to disk
            audio_io.seek(0)  # Reset the BytesIO stream again
            with open(output_path, "wb") as f:
                f.write(audio_io.read())

        return base64_audio

    def get_voices(self, model: Optional[str] = None) -> str:
        """
        Get available voices for a specific model.

        Args:
            model (Optional[str]): The model to get voices for. Defaults to None.
                                   Values can be "lightning" or "lightning-large".

        Returns:
            str: JSON string containing available voices with their metadata including:
                 - voiceId: Unique identifier for the voice
                 - displayName: Human-readable name
                 - tags: Information about the voice including:
                   - age: Age group of the voice
                   - emotions: List of emotions the voice can express
                   - language: Languages supported by the voice (e.g., "english", "hindi")
                   - usecases: Recommended use cases for the voice
                   - accent: Accent of the voice (e.g., "american", "british", "indian")
                   - gender: Gender of the voice
        """
        try:
            voices = self.smallest_client.get_voices(model=model)
            return str(voices)
        except Exception as e:
            logger.error(f"Failed to fetch voices: {e}")
            return f"Error: {e}"

    def get_languages(self) -> str:
        """
        Get available languages for TTS synthesis.

        Returns:
            str: JSON string containing available languages
        """
        try:
            languages = self.smallest_client.get_languages()
            return str(languages)
        except Exception as e:
            logger.error(f"Failed to fetch languages: {e}")
            return f"Error: {e}"

    def get_models(self) -> str:
        """
        Get available TTS models.

        Returns:
            str: JSON string containing available models.
        """
        try:
            models = self.smallest_client.get_models()
            return str(models)
        except Exception as e:
            logger.error(f"Failed to fetch models: {e}")
            return f"Error: {e}"

    def add_voice(self, display_name: str, file_path: str) -> str:
        """
        Add a cloned voice.

        Args:
            display_name (str): Name to display for the voice.
            file_path (str): Path to the audio file for voice cloning.

        Returns:
            str: JSON string containing the result of voice addition.
        """
        try:
            result = self.smallest_client.add_voice(display_name=display_name, file_path=file_path)
            return str(result)
        except Exception as e:
            logger.error(f"Failed to add voice: {e}")
            return f"Error: {e}"

    def text_to_speech(
        self,
        agent: Agent,
        prompt: str,
        voice_id: Optional[str] = None,
        model: Optional[SmallestAIModel] = None,
        sample_rate: Optional[int] = None,
        speed: Optional[float] = None,
        consistency: Optional[float] = None,
        similarity: Optional[float] = None,
        enhancement: Optional[int] = None,
    ) -> str:
        """
        Use this function to convert text to speech audio.

        Args:
            agent (Agent): The Agno agent to attach the audio to.
            prompt (str): Text to generate speech from.
            voice_id (Optional[str]): Voice ID to use. Defaults to None (uses the default voice).
                                      Examples:
                                         - American: "emily" (female), "james" (male), "george" (male narrative)
                                         - British: "karen" (female), "leo" (male)
                                         - Indian: "diya" (female, bilingual), "raj" (male, bilingual)
                                      Full list available through get_voices() method
            model (Optional[str]): TTS model to use. Options: "lightning" or "lightning-large". Defaults to "lightning".
            sample_rate (Optional[int]): Audio sample rate in Hz. Must be between 8000 and 24000. Default is 24000.
            speed (Optional[float]): Speech speed multiplier. Values between 0.5 and 2.0. Default is 1.0.
            consistency (Optional[float]): Controls word repetition and skipping. Values between 0.0 and 1.0.
                                          Decrease to prevent skipped words, increase to prevent repetition.
                                          Only supported in "lightning-large" model. Default is 0.5.
            similarity (Optional[float]): Controls similarity to reference audio. Values between 0.0 and 1.0.
                                         Higher values make speech more similar to reference audio.
                                         Only supported in "lightning-large" model. Default is 0.0.
            enhancement (Optional[int]): Enhances speech quality at cost of latency. Values between
                                         0 and 2, with higher values increasing enhancement.
                                         Only supported in "lightning-large" model. Default is 0.

        Returns:
            str: Status message indicating success or failure.
        """
        try:
            # Build kwargs with only non-None values
            kwargs = {}
            if voice_id is not None:
                kwargs["voice_id"] = voice_id
            if model is not None:
                kwargs["model"] = model
            if sample_rate is not None:
                kwargs["sample_rate"] = sample_rate  # type: ignore
            if speed is not None:
                kwargs["speed"] = speed  # type: ignore
            if consistency is not None and model == "lightning-large":
                kwargs["consistency"] = consistency  # type: ignore
            if similarity is not None and model == "lightning-large":
                kwargs["similarity"] = similarity  # type: ignore
            if enhancement is not None and model == "lightning-large":
                kwargs["enhancement"] = enhancement  # type: ignore

            # Generate the audio bytes
            audio_bytes = self.smallest_client.synthesize(text=prompt, **kwargs)

            # Process the audio and get base64 encoding
            base64_audio = self._process_audio(audio_bytes)

            # Attach to the agent
            agent.add_audio(
                AudioArtifact(
                    id=str(uuid4()),
                    base64_audio=base64_audio,
                    mime_type="audio/wav",
                )
            )

            return "Audio generated successfully"

        except Exception as e:
            logger.error(f"Failed to generate audio: {e}")
            return f"Error: {e}"
