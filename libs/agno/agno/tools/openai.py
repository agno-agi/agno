from typing import Literal

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

    def __init__(self, **kwargs):
        super().__init__(name="openai_tools", **kwargs)

        self.register(self.transcribe_audio)
        self.register(self.generate_image)
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

    def generate_image(self, prompt: str, n: int = 1, size: OpenAIImageSize = "1024x1024") -> str:
        """Generate images based on a text prompt using OpenAI's DALL-E API
        Args:
            prompt (str): The text prompt to generate the image from.
            n (int): The number of images to generate. Defaults to 1. Must be 1 for dall-e-3.
            size (OpenAIImageSize): The size of the generated images. Defaults to "1024x1024".
                Must be one of "1024x1024", "1792x1024", or "1024x1792" for dall-e-3.
                (Also supports "256x256", "512x512" for dall-e-2).

        Returns:
            str: A comma-separated string of URLs pointing to the generated images, or an error message.
        """
        log_info(f"Generating {n} image(s) of size {size} for prompt: '{prompt}'")
        try:
            # Actual API call
            response = client.images.generate(
                model="dall-e-3",  # Use dall-e-3
                prompt=prompt,
                n=n,  # Note: DALL-E 3 currently only supports n=1
                size=size,
                response_format="url",  # Request URLs instead of base64 data
            )
            image_urls = [item.url for item in response.data if item.url]  # Extract URLs
            result_string = ", ".join(image_urls)  # Convert list to comma-separated string
            log_info(f"Generated image URLs (as string): {result_string}")
            return result_string  # Return string instead of list
        except Exception as e:
            logger.error(f"Failed to generate image: {str(e)}")
            # Consider more specific error handling based on OpenAI exceptions if needed
            # e.g., from openai import APIError, RateLimitError, BadRequestError etc.
            return f"Failed to generate image: {str(e)}"  # Return error message as string

    def generate_speech(
        self,
        text_input: str,
        output_path: str,
        voice: OpenAIVoice = "alloy",
        model: OpenAITTSModel = "tts-1",
        response_format: OpenAITTSFormat = "mp3",
    ) -> str:
        """Generate speech from text using OpenAI's Text-to-Speech API and save it to a file.
        Args:
            text_input (str): The text to synthesize into speech.
            output_path (str): The file path where the generated audio will be saved.
            voice (OpenAIVoice): The voice to use. Defaults to "alloy".
            model (OpenAITTSModel): The TTS model to use. Defaults to "tts-1".
            response_format (OpenAITTSFormat): The format of the audio output. Defaults to "mp3".
                Supported formats: "mp3", "opus", "aac", "flac".

        Returns:
            str: The path to the saved audio file on success, or an error message string on failure.
        """
        log_info(
            f"Generating speech for text: '{text_input[:50]}...' with voice '{voice}', model '{model}', format '{response_format}' and saving to {output_path}"
        )
        try:
            response = client.audio.speech.create(
                model=model, voice=voice, input=text_input, response_format=response_format
            )
            response.stream_to_file(output_path)
            log_info(f"Speech saved successfully to {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Failed to generate speech: {str(e)}")
            return f"Failed to generate speech: {str(e)}"
