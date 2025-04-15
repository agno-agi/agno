from typing import Literal, Optional
from uuid import uuid4

from agno.agent import Agent
from agno.media import AudioArtifact, ImageArtifact
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, logger
from agno.utils.openai import _validate_image_params

try:
    from openai import OpenAI as OpenAIClient
except (ModuleNotFoundError, ImportError):
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


client = OpenAIClient()

# Define only types specifically needed by OpenAITools class
OpenAIVoice = Literal["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
OpenAITTSModel = Literal["tts-1", "tts-1-hd"]
OpenAITTSFormat = Literal["mp3", "opus", "aac", "flac", "wav", "pcm"]  # Aligned with client expectation


class OpenAITools(Toolkit):
    """Tools for interacting with OpenAIChat API"""

    def __init__(
        self,
        enable_transcription: bool = True,
        enable_image_generation: bool = True,
        enable_speech_generation: bool = True,
        text_to_speech_voice: OpenAIVoice = "alloy",
        text_to_speech_model: OpenAITTSModel = "tts-1",
        text_to_speech_format: OpenAITTSFormat = "mp3",
        image_generation_model: Optional[str] = "dall-e-3",
        image_generation_size: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(name="openai_tools", **kwargs)

        # Store TTS defaults
        self.tts_voice = text_to_speech_voice
        self.tts_model = text_to_speech_model
        self.tts_format = text_to_speech_format

        # Validate and store Image Generation defaults
        try:
            self.image_model = image_generation_model
            self.image_size = _validate_image_params(image_generation_model, image_generation_size)
        except ValueError as e:
            logger.error(f"Initialization failed: {e}")
            raise

        if enable_transcription:
            self.register(self.transcribe_audio)
        if enable_image_generation:
            self.register(self.generate_image)
        if enable_speech_generation:
            self.register(self.generate_speech)

    def transcribe_audio(self, audio_path: str) -> str:
        """Transcribe audio file using OpenAI's Whisper API
        Args:
            audio_path: Path to the audio file
        Returns:
            str: Transcribed text
        """
        log_info(f"Transcribing audio from {audio_path}")
        try:
            with open(audio_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1", file=audio_file, response_format="srt"
                )
                log_info(f"Transcript: {transcript}")
            return transcript
        except Exception as e:
            logger.error(f"Failed to transcribe audio: {str(e)}")
            return f"Failed to transcribe audio: {str(e)}"

    def generate_image(
        self,
        agent: Agent,
        prompt: str,
        number_of_images: int = 1,
        output_file_path: Optional[str] = None,  # Optional path to save the image file (only if n=1)
    ) -> str:
        """Generate images based on a text prompt using OpenAI's DALL-E API

        Uses the model and size configured during Toolkit initialization.
        Optionally saves the generated image directly to a file if n=1.

        Args:
            agent (Agent): The agent to add the generated images to.
            prompt (str): The text prompt to generate the image from.
            n (int): The number of images to generate. Defaults to 1. Must be 1 for dall-e-3.
            output_file_path (Optional[str]): If provided and n=1, the path where the generated image file will be saved.

        Returns:
            str: A comma-separated string of URLs pointing to the generated images, or an error message.
        """

        # Input validation (size vs model) is now handled in __init__
        # Ensure n=1 for dall-e-3
        if self.image_model == "dall-e-3" and number_of_images != 1:
            logger.warning("DALL-E 3 only supports n=1. Forcing n=1.")
            number_of_images = 1

        # Warn if output path provided but n > 1
        if output_file_path and number_of_images > 1:
            logger.warning(
                f"Output file path '{output_file_path}' provided, but number_of_images > 1. Image saving will be skipped."
            )

        # --- API Call ---
        try:
            response = client.images.generate(
                model=self.image_model,
                prompt=prompt,
                n=number_of_images,
                size=self.image_size,
                response_format="url",
            )
            image_urls = [item.url for item in response.data if item.url]

            # Save the image to a file if path is provided and n=1
            if output_file_path and number_of_images == 1 and image_urls:
                try:
                    from pathlib import Path

                    import httpx

                    image_url_to_save = image_urls[0]  # Get the first (only) URL
                    image_file_path = Path(output_file_path)
                    image_file_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure directory exists

                    # Download image data
                    with httpx.Client() as http_client:
                        http_response = http_client.get(image_url_to_save)
                        http_response.raise_for_status()  # Raise exception for bad status codes
                        image_data: bytes = http_response.content

                    # Write image data to file
                    with open(image_file_path, "wb") as f:
                        f.write(image_data)
                    log_info(f"Successfully saved image to {image_file_path}")

                except ImportError:
                    logger.error("'httpx' library is required to save images from URL. Please install it.")
                except Exception as e_save:
                    logger.error(f"Failed to save image to file '{output_file_path}': {str(e_save)}")
                    # Log error but continue with artifact creation

            # Add images to agent context
            for url in image_urls:
                if url:  # Ensure URL is not empty
                    media_id = str(uuid4())
                    agent.add_image(
                        ImageArtifact(
                            id=media_id,
                            url=url,
                            prompt=prompt,  # Optionally add prompt context
                            model=self.image_model,
                        )
                    )
                    log_debug(f"Added generated image artifact {media_id} to agent.")

            result_string = ", ".join(image_urls)
            log_info(f"Generated image URLs using {self.image_model}: {result_string}")
            return result_string
        except Exception as e:
            logger.error(f"Failed to generate image using {self.image_model}: {str(e)}")
            return f"Failed to generate image using {self.image_model}: {str(e)}"

    def generate_speech(
        self,
        agent: Agent,
        text_input: str,
        output_file_path: Optional[str] = None,  # Optional path to save the audio file
    ) -> str:
        """Generate speech from text using OpenAI's Text-to-Speech API.
        Optionally saves the generated audio directly to a file.

        Args:
            agent (Agent): The agent instance to add the artifact to.
            text_input (str): The text to synthesize into speech.
            output_file_path (Optional[str]): If provided, the path where the generated audio file will be saved.

        Returns:
            str: The ID of the generated audio artifact on success, or an error message string on failure.
        """
        try:
            import base64
            from pathlib import Path

            response = client.audio.speech.create(
                model=self.tts_model, voice=self.tts_voice, input=text_input, response_format=self.tts_format
            )

            # Save the audio to a file if path is provided
            if output_file_path:
                try:
                    speech_file_path = Path(output_file_path)
                    speech_file_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
                    response.stream_to_file(speech_file_path)
                    log_info(f"Successfully saved speech to {speech_file_path}")
                except Exception as e_save:
                    logger.error(f"Failed to save speech to file '{output_file_path}': {str(e_save)}")
                    # Decide if failure to save should stop the process or just be logged
                    # For now, we log the error and continue to create the artifact

            # Get raw audio data for artifact creation
            audio_data: bytes = response.content

            # Base64 encode the audio data
            base64_encoded_audio = base64.b64encode(audio_data).decode("utf-8")

            # Create and add AudioArtifact using base64_audio field
            media_id = str(uuid4())
            agent.add_audio(
                AudioArtifact(
                    id=media_id,
                    base64_audio=base64_encoded_audio,
                    format=self.tts_format,
                    model=self.tts_model,
                    voice=self.tts_voice,
                )
            )
            log_info(f"Added generated audio artifact {media_id} to agent.")
            return media_id
        except Exception as e:
            logger.error(f"Failed to generate speech: {str(e)}")
            return f"Failed to generate speech: {str(e)}"
