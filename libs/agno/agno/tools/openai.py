from typing import Literal
from uuid import uuid4

from agno.agent import Agent
from agno.media import AudioArtifact, ImageArtifact
from agno.tools import Toolkit
from agno.utils.log import log_info, logger

try:
    from openai import OpenAI as OpenAIClient
except (ModuleNotFoundError, ImportError):
    raise ImportError("`openai` not installed. Please install using `pip install openai`")


client = OpenAIClient()

# Define Literal types for allowed OpenAI parameter values
OpenAIImageSize = Literal["256x256", "512x512", "1024x1024", "1792x1024", "1024x1792"]
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
        default_tts_voice: OpenAIVoice = "alloy",
        default_tts_model: OpenAITTSModel = "tts-1",
        default_tts_format: OpenAITTSFormat = "mp3",
        **kwargs,
    ):
        super().__init__(name="openai_tools", **kwargs)

        # Store TTS defaults
        self.tts_voice = default_tts_voice
        self.tts_model = default_tts_model
        self.tts_format = default_tts_format

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
        model_name: Literal["dall-e-2", "dall-e-3"] = "dall-e-3",
        n: int = 1,
        size: OpenAIImageSize = "1024x1024",
    ) -> str:
        """Generate images based on a text prompt using OpenAI's DALL-E API
        Args:
            agent (Agent): The agent to add the generated images to.
            prompt (str): The text prompt to generate the image from.
            model_name (Literal["dall-e-2", "dall-e-3"]): The DALL-E model to use. Defaults to "dall-e-3".
            n (int): The number of images to generate. Defaults to 1. Must be 1 for dall-e-3.
            size (OpenAIImageSize): The size of the generated images. Defaults to "1024x1024".
                - For dall-e-2: Must be one of "256x256", "512x512", or "1024x1024".
                - For dall-e-3: Must be one of "1024x1024", "1792x1024", or "1024x1792".

        Returns:
            str: A comma-separated string of URLs pointing to the generated images, or an error message.
        """
        log_info(f"Generating {n} image(s) using {model_name} of size {size} for prompt: '{prompt}'")

        if model_name == "dall-e-3":
            if n != 1:
                logger.warning("DALL-E 3 only supports n=1. Forcing n=1.")
                n = 1  # Force n=1 for DALL-E 3
            if size not in ["1024x1024", "1792x1024", "1024x1792"]:
                error_msg = f"Invalid size '{size}' for DALL-E 3. Must be '1024x1024', '1792x1024', or '1024x1792'."
                logger.error(error_msg)
                return error_msg
        elif model_name == "dall-e-2":
            if size not in ["256x256", "512x512", "1024x1024"]:
                error_msg = f"Invalid size '{size}' for DALL-E 2. Must be '256x256', '512x512', or '1024x1024'."
                logger.error(error_msg)
                return error_msg

        # --- API Call ---
        try:
            response = client.images.generate(
                model=model_name,
                prompt=prompt,
                n=n,
                size=size,
                response_format="url",
            )
            image_urls = [item.url for item in response.data if item.url]

            # Add images to agent context
            for url in image_urls:
                if url:  # Ensure URL is not empty
                    media_id = str(uuid4())
                    agent.add_image(
                        ImageArtifact(
                            id=media_id,
                            url=url,
                            prompt=prompt,  # Optionally add prompt context
                            model=model_name,  # Optionally add model context
                        )
                    )
                    log_info(f"Added generated image artifact {media_id} to agent.")

            result_string = ", ".join(image_urls)
            log_info(f"Generated image URLs (as string): {result_string}")
            return result_string
        except Exception as e:
            logger.error(f"Failed to generate image using {model_name}: {str(e)}")
            return f"Failed to generate image using {model_name}: {str(e)}"

    def generate_speech(
        self,
        agent: Agent,
        text_input: str,
    ) -> str:
        """Generate speech from text using OpenAI's Text-to-Speech API.
        Adds the generated audio as an AudioArtifact to the agent's context.
        Uses the voice, model, and format specified during OpenAITools initialization.
        Args:
            agent (Agent): The agent instance to add the audio artifact to.
            text_input (str): The text to synthesize into speech.

        Returns:
            str: The ID of the generated audio artifact on success, or an error message string on failure.
        """
        log_info(
            f"Generating speech for text: '{text_input[:50]}...' with voice '{self.tts_voice}', model '{self.tts_model}', format '{self.tts_format}'"
        )
        try:
            import base64

            response = client.audio.speech.create(
                model=self.tts_model, voice=self.tts_voice, input=text_input, response_format=self.tts_format
            )
            # Get raw audio data
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
