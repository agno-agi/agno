import base64
import os
from os import getenv
from typing import Optional
from uuid import uuid4

from agno.agent import Agent
from agno.media import AudioArtifact
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    from groq import Groq as GroqClient
except (ModuleNotFoundError, ImportError):
    raise ImportError("`groq` not installed. Please install using `pip install groq`")


class GroqTools(Toolkit):
    """Tools for interacting with Groq API"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        transcription_model: str = "whisper-large-v3",
        translation_model: str = "whisper-large-v3",
        tts_model: str = "playai-tts",
        tts_voice: str = "Chip-PlayAI",
        **kwargs,
    ):
        super().__init__(
            name="groq_tools", tools=[self.transcribe_audio, self.translate_audio, self.generate_speech], **kwargs
        )

        self.api_key = api_key or getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY not set. Please set the GROQ_API_KEY environment variable.")

        self.client = GroqClient(api_key=self.api_key)
        self.transcription_model = transcription_model
        self.translation_model = translation_model
        self.tts_model = tts_model
        self.tts_voice = tts_voice
        self.tts_format = "wav"

    def transcribe_audio(self, audio_source: str) -> str:
        """Transcribe audio file or URL using Groq's Whisper API.
        Args:
            audio_source: Path to the local audio file or a publicly accessible URL to the audio.
        Returns:
            str: Transcribed text
        """
        log_debug(f"Transcribing audio from {audio_source} using Groq model {self.transcription_model}")
        try:
            # Check if the audio source as a local file or a URL
            if not os.path.exists(audio_source):
                log_debug(f"Audio source '{audio_source}' not found locally, attempting as URL.")
                transcription_text = self.client.audio.transcriptions.create(
                    url=audio_source,
                    model=self.transcription_model,
                    response_format="text",
                )
            else:
                log_debug(f"Transcribing local file: {audio_source}")
                with open(audio_source, "rb") as audio_file:
                    transcription_text = self.client.audio.transcriptions.create(
                        file=(os.path.basename(audio_source), audio_file.read()),
                        model=self.transcription_model,
                        response_format="text",
                    )
            log_debug(f"Transcript Generated: {transcription_text}")
            return str(transcription_text)

        except Exception as e:
            log_error(f"Failed to transcribe audio source '{audio_source}' with Groq: {str(e)}")
            return f"Failed to transcribe audio source '{audio_source}' with Groq: {str(e)}"

    def translate_audio(self, audio_source: str) -> str:
        """Translate audio file or URL to English using Groq's Whisper API.
        Args:
            audio_source: Path to the local audio file or a publicly accessible URL to the audio.
        Returns:
            str: Translated English text
        """
        log_debug(f"Translating audio from {audio_source} to English using Groq model {self.translation_model}")
        try:
            if not os.path.exists(audio_source):
                log_debug(f"Audio source '{audio_source}' not found locally.")
                translation = self.client.audio.translations.create(
                    url=audio_source,
                    model=self.translation_model,
                    response_format="text",
                )
            else:
                log_debug(f"Translating local file: {audio_source}")
                with open(audio_source, "rb") as audio_file:
                    translation = self.client.audio.translations.create(
                        file=(os.path.basename(audio_source), audio_file.read()),
                        model=self.translation_model,
                        response_format="text",
                    )
            log_debug(f"Groq Translation: {translation}")
            return str(translation)

        except Exception as e:
            log_error(f"Failed to translate audio source '{audio_source}' with Groq: {str(e)}")
            return f"Failed to translate audio source '{audio_source}' with Groq: {str(e)}"

    def generate_speech(
        self,
        agent: Agent,
        text_input: str,
    ) -> str:
        """Generate speech from text using Groq's Text-to-Speech API.
        Adds the generated audio as an AudioArtifact to the agent.

        Args:
            text_input: The text to synthesize into speech.
        Returns:
            str: A success message with the audio artifact ID or an error message.
        """
        log_debug(
            f"Generating speech for text: '{text_input[:50]}...' using Groq model {self.tts_model}, voice {self.tts_voice}"
        )

        try:
            response = self.client.audio.speech.create(
                model=self.tts_model,
                voice=self.tts_voice,
                input=text_input,
                response_format="wav",
            )

            log_debug(f"Groq TTS Response: {response}")

            audio_data: bytes = response.read()
            base64_encoded_audio = base64.b64encode(audio_data).decode("utf-8")

            media_id = str(uuid4())
            agent.add_audio(
                AudioArtifact(
                    id=media_id,
                    base64_audio=base64_encoded_audio,
                    mime_type="audio/wav",
                )
            )
            log_debug(f"Successfully generated speech artifact with ID: {media_id}")
            return f"Speech generated successfully with ID: {media_id}"

        except Exception as e:
            log_error(f"Failed to generate speech with Groq: {str(e)}")
            return f"Failed to generate speech with Groq: {str(e)}"
