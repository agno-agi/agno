"""CAMB AI toolkit for agno.

Provides 9 audio/speech tools powered by CAMB AI:
- Text-to-Speech (TTS)
- Translation
- Transcription
- Translated TTS
- Voice Cloning
- Voice Listing
- Voice Creation from Description
- Text-to-Sound generation
- Audio Separation
"""

import base64
import json
import struct
import tempfile
import time
from os import getenv
from typing import Any, Dict, List, Literal, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, logger

try:
    from camb.client import AsyncCambAI, CambAI
except ImportError:
    raise ImportError("`camb-sdk` not installed. Please install using `pip install 'agno[camb]'`")


class CambTools(Toolkit):
    """Toolkit for CAMB AI audio and speech services.

    CAMB AI provides multilingual audio and localization services including
    text-to-speech, translation, transcription, voice cloning, text-to-sound
    generation, and audio separation across 140+ languages.

    Args:
        api_key: CAMB AI API key. Falls back to CAMB_API_KEY env var.
        base_url: Optional custom base URL for CAMB AI API.
        timeout: Request timeout in seconds.
        max_poll_attempts: Maximum polling attempts for async tasks.
        poll_interval: Seconds between polling attempts.
        enable_tts: Enable text-to-speech tool.
        enable_translation: Enable translation tool.
        enable_transcription: Enable transcription tool.
        enable_translated_tts: Enable translated TTS tool.
        enable_voice_clone: Enable voice cloning tool.
        enable_voice_list: Enable voice listing tool.
        enable_voice_from_description: Enable voice creation from description tool.
        enable_text_to_sound: Enable text-to-sound tool.
        enable_audio_separation: Enable audio separation tool.
        all: Enable all tools (overrides individual flags).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        max_poll_attempts: int = 60,
        poll_interval: float = 2.0,
        enable_tts: bool = True,
        enable_translation: bool = True,
        enable_transcription: bool = True,
        enable_translated_tts: bool = True,
        enable_voice_clone: bool = True,
        enable_voice_list: bool = True,
        enable_voice_from_description: bool = True,
        enable_text_to_sound: bool = True,
        enable_audio_separation: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("CAMB_API_KEY")
        if not self.api_key:
            raise ValueError("CAMB_API_KEY not set. Please set the CAMB_API_KEY environment variable.")

        self.base_url = base_url
        self.timeout = timeout
        self.max_poll_attempts = max_poll_attempts
        self.poll_interval = poll_interval

        client_kwargs: Dict[str, Any] = {"api_key": self.api_key, "timeout": self.timeout}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        self._sync_client = CambAI(**client_kwargs)
        self._async_client = AsyncCambAI(**client_kwargs)

        tools: List[Any] = []
        async_tools: List[Any] = []

        if all or enable_tts:
            tools.append(self.text_to_speech)
            async_tools.append((self.async_text_to_speech, "text_to_speech"))
        if all or enable_translation:
            tools.append(self.translate)
            async_tools.append((self.async_translate, "translate"))
        if all or enable_transcription:
            tools.append(self.transcribe)
            async_tools.append((self.async_transcribe, "transcribe"))
        if all or enable_translated_tts:
            tools.append(self.translated_tts)
            async_tools.append((self.async_translated_tts, "translated_tts"))
        if all or enable_voice_clone:
            tools.append(self.clone_voice)
        if all or enable_voice_list:
            tools.append(self.list_voices)
            async_tools.append((self.async_list_voices, "list_voices"))
        if all or enable_voice_from_description:
            tools.append(self.create_voice_from_description)
            async_tools.append((self.async_create_voice_from_description, "create_voice_from_description"))
        if all or enable_text_to_sound:
            tools.append(self.text_to_sound)
            async_tools.append((self.async_text_to_sound, "text_to_sound"))
        if all or enable_audio_separation:
            tools.append(self.separate_audio)
            async_tools.append((self.async_separate_audio, "separate_audio"))

        super().__init__(name="camb_tools", tools=tools, async_tools=async_tools, **kwargs)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _poll_sync(self, get_status_fn, task_id, *, run_id=None):
        """Poll a CAMB AI async task until completion."""
        for _ in range(self.max_poll_attempts):
            status = get_status_fn(task_id, run_id=run_id)
            if hasattr(status, "status"):
                val = status.status
                if val in ("completed", "SUCCESS"):
                    return status
                if val in ("failed", "FAILED", "error"):
                    raise RuntimeError(f"Task failed: {getattr(status, 'error', 'Unknown error')}")
            time.sleep(self.poll_interval)
        raise TimeoutError(f"Task {task_id} did not complete within {self.max_poll_attempts * self.poll_interval}s")

    async def _poll_async(self, get_status_fn, task_id, *, run_id=None):
        """Poll a CAMB AI async task until completion (async)."""
        import asyncio

        for _ in range(self.max_poll_attempts):
            status = await get_status_fn(task_id, run_id=run_id)
            if hasattr(status, "status"):
                val = status.status
                if val in ("completed", "SUCCESS"):
                    return status
                if val in ("failed", "FAILED", "error"):
                    raise RuntimeError(f"Task failed: {getattr(status, 'error', 'Unknown error')}")
            await asyncio.sleep(self.poll_interval)
        raise TimeoutError(f"Task {task_id} did not complete within {self.max_poll_attempts * self.poll_interval}s")

    @staticmethod
    def _detect_audio_format(data: bytes, content_type: str = "") -> str:
        if data.startswith(b"RIFF"):
            return "wav"
        if data.startswith((b"\xff\xfb", b"\xff\xfa", b"ID3")):
            return "mp3"
        if data.startswith(b"fLaC"):
            return "flac"
        if data.startswith(b"OggS"):
            return "ogg"
        ct = content_type.lower()
        for key, fmt in [("wav", "wav"), ("wave", "wav"), ("mpeg", "mp3"), ("mp3", "mp3"), ("flac", "flac"), ("ogg", "ogg")]:
            if key in ct:
                return fmt
        return "pcm"

    @staticmethod
    def _add_wav_header(pcm_data: bytes) -> bytes:
        sr, ch, bps = 24000, 1, 16
        byte_rate = sr * ch * bps // 8
        block_align = ch * bps // 8
        data_size = len(pcm_data)
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF", 36 + data_size, b"WAVE", b"fmt ", 16, 1,
            ch, sr, byte_rate, block_align, bps, b"data", data_size,
        )
        return header + pcm_data

    @staticmethod
    def _save_audio(data: bytes, suffix: str = ".wav") -> str:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(data)
            return f.name

    @staticmethod
    def _gender_str(g: int) -> str:
        return {0: "not_specified", 1: "male", 2: "female", 9: "not_applicable"}.get(g, "unknown")

    # ------------------------------------------------------------------
    # 1. Text-to-Speech
    # ------------------------------------------------------------------

    def text_to_speech(
        self,
        text: str,
        language: str = "en-us",
        voice_id: int = 147320,
        speech_model: str = "mars-flash",
        speed: float = 1.0,
        user_instructions: Optional[str] = None,
    ) -> str:
        """Convert text to speech using CAMB AI. Supports 140+ languages and multiple voice models.

        Use this tool to generate spoken audio from text. The audio is saved to a temporary file
        and the file path is returned. Available speech models: 'mars-flash' (fast),
        'mars-pro' (high quality), 'mars-instruct' (follows user_instructions).

        Args:
            text: Text to convert to speech (3-3000 characters).
            language: BCP-47 language code (e.g., 'en-us', 'es-es', 'fr-fr').
            voice_id: Voice ID. Use list_voices to find available voices.
            speech_model: Speech model: 'mars-flash', 'mars-pro', or 'mars-instruct'.
            speed: Speech speed multiplier (0.5-2.0).
            user_instructions: Instructions for mars-instruct model (e.g., 'Speak with excitement').

        Returns:
            str: File path to the generated audio file.
        """
        from camb import StreamTtsOutputConfiguration, StreamTtsVoiceSettings

        kwargs: Dict[str, Any] = {
            "text": text, "language": language, "voice_id": voice_id,
            "speech_model": speech_model,
            "output_configuration": StreamTtsOutputConfiguration(format="wav"),
            "voice_settings": StreamTtsVoiceSettings(speed=speed),
        }
        if user_instructions and speech_model == "mars-instruct":
            kwargs["user_instructions"] = user_instructions

        log_debug(f"CAMB TTS: generating speech for text length {len(text)}")
        chunks: list[bytes] = []
        for chunk in self._sync_client.text_to_speech.tts(**kwargs):
            chunks.append(chunk)
        path = self._save_audio(b"".join(chunks), ".wav")
        log_info(f"CAMB TTS: audio saved to {path}")
        return path

    async def async_text_to_speech(
        self,
        text: str,
        language: str = "en-us",
        voice_id: int = 147320,
        speech_model: str = "mars-flash",
        speed: float = 1.0,
        user_instructions: Optional[str] = None,
    ) -> str:
        """Convert text to speech using CAMB AI (async version).

        Args:
            text: Text to convert to speech (3-3000 characters).
            language: BCP-47 language code.
            voice_id: Voice ID.
            speech_model: Speech model.
            speed: Speech speed multiplier (0.5-2.0).
            user_instructions: Instructions for mars-instruct model.

        Returns:
            str: File path to the generated audio file.
        """
        from camb import StreamTtsOutputConfiguration, StreamTtsVoiceSettings

        kwargs: Dict[str, Any] = {
            "text": text, "language": language, "voice_id": voice_id,
            "speech_model": speech_model,
            "output_configuration": StreamTtsOutputConfiguration(format="wav"),
            "voice_settings": StreamTtsVoiceSettings(speed=speed),
        }
        if user_instructions and speech_model == "mars-instruct":
            kwargs["user_instructions"] = user_instructions

        chunks: list[bytes] = []
        async for chunk in self._async_client.text_to_speech.tts(**kwargs):
            chunks.append(chunk)
        return self._save_audio(b"".join(chunks), ".wav")

    # ------------------------------------------------------------------
    # 2. Translation
    # ------------------------------------------------------------------

    def translate(
        self,
        text: str,
        source_language: int,
        target_language: int,
        formality: Optional[int] = None,
    ) -> str:
        """Translate text between 140+ languages using CAMB AI.

        Use this tool to translate text from one language to another. Provide integer
        language codes: 1=English, 2=Spanish, 3=French, 4=German, 5=Italian,
        6=Portuguese, 7=Dutch, 8=Russian, 9=Japanese, 10=Korean, 11=Chinese.

        Args:
            text: Text to translate.
            source_language: Source language code (integer).
            target_language: Target language code (integer).
            formality: Optional formality level: 1=formal, 2=informal.

        Returns:
            str: The translated text.
        """
        from camb.core.api_error import ApiError

        kwargs: Dict[str, Any] = {
            "text": text, "source_language": source_language,
            "target_language": target_language,
        }
        if formality:
            kwargs["formality"] = formality

        try:
            result = self._sync_client.translation.translation_stream(**kwargs)
            return self._extract_translation(result)
        except ApiError as e:
            if e.status_code == 200 and e.body:
                return str(e.body)
            raise

    async def async_translate(
        self,
        text: str,
        source_language: int,
        target_language: int,
        formality: Optional[int] = None,
    ) -> str:
        """Translate text between 140+ languages using CAMB AI (async version).

        Args:
            text: Text to translate.
            source_language: Source language code (integer).
            target_language: Target language code (integer).
            formality: Optional formality level: 1=formal, 2=informal.

        Returns:
            str: The translated text.
        """
        from camb.core.api_error import ApiError

        kwargs: Dict[str, Any] = {
            "text": text, "source_language": source_language,
            "target_language": target_language,
        }
        if formality:
            kwargs["formality"] = formality

        try:
            result = await self._async_client.translation.translation_stream(**kwargs)
            return self._extract_translation(result)
        except ApiError as e:
            if e.status_code == 200 and e.body:
                return str(e.body)
            raise

    @staticmethod
    def _extract_translation(result) -> str:
        if hasattr(result, "__iter__") and not isinstance(result, (str, bytes)):
            parts = []
            for chunk in result:
                if hasattr(chunk, "text"):
                    parts.append(chunk.text)
                elif isinstance(chunk, str):
                    parts.append(chunk)
            return "".join(parts)
        if hasattr(result, "text"):
            return result.text
        return str(result)

    # ------------------------------------------------------------------
    # 3. Transcription
    # ------------------------------------------------------------------

    def transcribe(
        self,
        language: int,
        audio_url: Optional[str] = None,
        audio_file_path: Optional[str] = None,
    ) -> str:
        """Transcribe audio to text with speaker identification using CAMB AI.

        Use this tool to convert speech in an audio file to text. Supports audio URLs
        or local file paths. Returns JSON with full transcription text, timed segments,
        and speaker labels.

        Args:
            language: Language code (integer). 1=English, 2=Spanish, 3=French, etc.
            audio_url: URL of the audio file to transcribe.
            audio_file_path: Local file path to the audio file.

        Returns:
            str: JSON string with text, segments (start, end, text, speaker), and speakers list.
        """
        kwargs: Dict[str, Any] = {"language": language}

        if audio_url:
            import httpx

            resp = httpx.get(audio_url)
            resp.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name
            with open(tmp_path, "rb") as f:
                kwargs["media_file"] = f
                result = self._sync_client.transcription.create_transcription(**kwargs)
        elif audio_file_path:
            with open(audio_file_path, "rb") as f:
                kwargs["media_file"] = f
                result = self._sync_client.transcription.create_transcription(**kwargs)
        else:
            return json.dumps({"error": "Provide either audio_url or audio_file_path"})

        task_id = result.task_id
        status = self._poll_sync(self._sync_client.transcription.get_transcription_task_status, task_id)
        transcription = self._sync_client.transcription.get_transcription_result(status.run_id)
        return self._format_transcription(transcription)

    async def async_transcribe(
        self,
        language: int,
        audio_url: Optional[str] = None,
        audio_file_path: Optional[str] = None,
    ) -> str:
        """Transcribe audio to text using CAMB AI (async version).

        Args:
            language: Language code (integer).
            audio_url: URL of the audio file.
            audio_file_path: Local file path to the audio file.

        Returns:
            str: JSON string with transcription results.
        """
        kwargs: Dict[str, Any] = {"language": language}

        if audio_url:
            import httpx

            async with httpx.AsyncClient() as http:
                resp = await http.get(audio_url)
                resp.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name
            with open(tmp_path, "rb") as f:
                kwargs["media_file"] = f
                result = await self._async_client.transcription.create_transcription(**kwargs)
        elif audio_file_path:
            with open(audio_file_path, "rb") as f:
                kwargs["media_file"] = f
                result = await self._async_client.transcription.create_transcription(**kwargs)
        else:
            return json.dumps({"error": "Provide either audio_url or audio_file_path"})

        task_id = result.task_id
        status = await self._poll_async(self._async_client.transcription.get_transcription_task_status, task_id)
        transcription = await self._async_client.transcription.get_transcription_result(status.run_id)
        return self._format_transcription(transcription)

    @staticmethod
    def _format_transcription(transcription) -> str:
        out: Dict[str, Any] = {"text": getattr(transcription, "text", ""), "segments": [], "speakers": []}
        if hasattr(transcription, "segments"):
            for seg in transcription.segments:
                out["segments"].append({
                    "start": getattr(seg, "start", 0), "end": getattr(seg, "end", 0),
                    "text": getattr(seg, "text", ""), "speaker": getattr(seg, "speaker", None),
                })
        if hasattr(transcription, "speakers"):
            out["speakers"] = list(transcription.speakers)
        elif out["segments"]:
            out["speakers"] = list({s["speaker"] for s in out["segments"] if s.get("speaker")})
        return json.dumps(out, indent=2)

    # ------------------------------------------------------------------
    # 4. Translated TTS
    # ------------------------------------------------------------------

    def translated_tts(
        self,
        text: str,
        source_language: int,
        target_language: int,
        voice_id: int = 147320,
        formality: Optional[int] = None,
    ) -> str:
        """Translate text and convert to speech in one step using CAMB AI.

        Use this tool to translate text to a target language and generate speech audio
        in that language. Returns the file path to the audio file.

        Args:
            text: Text to translate and speak.
            source_language: Source language code (integer).
            target_language: Target language code (integer).
            voice_id: Voice ID for TTS output.
            formality: Optional formality: 1=formal, 2=informal.

        Returns:
            str: File path to the audio file of translated speech.
        """
        kwargs: Dict[str, Any] = {
            "text": text, "voice_id": voice_id,
            "source_language": source_language, "target_language": target_language,
        }
        if formality:
            kwargs["formality"] = formality

        result = self._sync_client.translated_tts.create_translated_tts(**kwargs)
        status = self._poll_sync(self._sync_client.translated_tts.get_translated_tts_task_status, result.task_id)
        audio_data, fmt = self._fetch_translated_audio(status, sync=True)

        if fmt == "pcm" and audio_data:
            audio_data = self._add_wav_header(audio_data)
            fmt = "wav"

        ext = {"wav": ".wav", "mp3": ".mp3", "flac": ".flac", "ogg": ".ogg"}.get(fmt, ".wav")
        return self._save_audio(audio_data, ext)

    async def async_translated_tts(
        self,
        text: str,
        source_language: int,
        target_language: int,
        voice_id: int = 147320,
        formality: Optional[int] = None,
    ) -> str:
        """Translate text and convert to speech using CAMB AI (async version).

        Args:
            text: Text to translate and speak.
            source_language: Source language code (integer).
            target_language: Target language code (integer).
            voice_id: Voice ID for TTS output.
            formality: Optional formality.

        Returns:
            str: File path to the audio file.
        """
        kwargs: Dict[str, Any] = {
            "text": text, "voice_id": voice_id,
            "source_language": source_language, "target_language": target_language,
        }
        if formality:
            kwargs["formality"] = formality

        result = await self._async_client.translated_tts.create_translated_tts(**kwargs)
        status = await self._poll_async(
            self._async_client.translated_tts.get_translated_tts_task_status, result.task_id
        )
        audio_data, fmt = await self._fetch_translated_audio(status, sync=False)

        if fmt == "pcm" and audio_data:
            audio_data = self._add_wav_header(audio_data)
            fmt = "wav"

        ext = {"wav": ".wav", "mp3": ".mp3", "flac": ".flac", "ogg": ".ogg"}.get(fmt, ".wav")
        return self._save_audio(audio_data, ext)

    def _fetch_translated_audio(self, status, *, sync: bool = True):
        """Download translated TTS audio via httpx (SDK workaround)."""
        import httpx

        run_id = getattr(status, "run_id", None)
        if run_id:
            client_obj = self._sync_client if sync else self._async_client
            base = getattr(client_obj, "_client_wrapper", None)
            if base and hasattr(base, "base_url"):
                url = f"{base.base_url}/tts-result/{run_id}"
            else:
                url = f"https://client.camb.ai/apis/tts-result/{run_id}"

            if sync:
                with httpx.Client() as http:
                    resp = http.get(url, headers={"x-api-key": self.api_key})
                    if resp.status_code == 200:
                        fmt = self._detect_audio_format(resp.content, resp.headers.get("content-type", ""))
                        return resp.content, fmt
            else:
                import asyncio

                async def _fetch():
                    async with httpx.AsyncClient() as http:
                        resp = await http.get(url, headers={"x-api-key": self.api_key})
                        if resp.status_code == 200:
                            fmt = self._detect_audio_format(resp.content, resp.headers.get("content-type", ""))
                            return resp.content, fmt
                    return b"", "pcm"

                return _fetch()

        # Fallback: check status message for URL
        message = getattr(status, "message", None)
        if message:
            msg_url = None
            if isinstance(message, dict):
                msg_url = message.get("output_url") or message.get("audio_url") or message.get("url")
            elif isinstance(message, str) and message.startswith("http"):
                msg_url = message

            if msg_url:
                if sync:
                    with httpx.Client() as http:
                        resp = http.get(msg_url)
                        fmt = self._detect_audio_format(resp.content, resp.headers.get("content-type", ""))
                        return resp.content, fmt
                else:
                    async def _fetch_url():
                        async with httpx.AsyncClient() as http:
                            resp = await http.get(msg_url)
                            fmt = self._detect_audio_format(resp.content, resp.headers.get("content-type", ""))
                            return resp.content, fmt

                    return _fetch_url()

        if sync:
            return b"", "pcm"

        async def _empty():
            return b"", "pcm"

        return _empty()

    # ------------------------------------------------------------------
    # 5. Voice Cloning
    # ------------------------------------------------------------------

    def clone_voice(
        self,
        voice_name: str,
        audio_file_path: str,
        gender: int,
        description: Optional[str] = None,
        age: Optional[int] = None,
        language: Optional[int] = None,
    ) -> str:
        """Clone a voice from an audio sample using CAMB AI.

        Use this tool to create a custom voice from a 2+ second audio sample. The cloned
        voice can then be used with text_to_speech and translated_tts tools.

        Args:
            voice_name: Name for the new cloned voice.
            audio_file_path: Path to audio file (minimum 2 seconds).
            gender: Gender: 1=Male, 2=Female, 0=Not Specified, 9=Not Applicable.
            description: Optional description of the voice.
            age: Optional age of the voice.
            language: Optional language code for the voice.

        Returns:
            str: JSON string with voice_id, voice_name, and status.
        """
        with open(audio_file_path, "rb") as f:
            kwargs: Dict[str, Any] = {"voice_name": voice_name, "gender": gender, "file": f}
            if description:
                kwargs["description"] = description
            if age:
                kwargs["age"] = age
            if language:
                kwargs["language"] = language
            result = self._sync_client.voice_cloning.create_custom_voice(**kwargs)

        out = {
            "voice_id": getattr(result, "voice_id", getattr(result, "id", None)),
            "voice_name": voice_name, "status": "created",
        }
        if hasattr(result, "message"):
            out["message"] = result.message
        return json.dumps(out, indent=2)

    # ------------------------------------------------------------------
    # 6. Voice Listing
    # ------------------------------------------------------------------

    def list_voices(self) -> str:
        """List all available voices from CAMB AI.

        Use this tool to discover available voices for text-to-speech. Returns voice IDs,
        names, genders, ages, and languages. Use the voice ID with text_to_speech or
        translated_tts tools.

        Returns:
            str: JSON array of voice objects with id, name, gender, age, and language.
        """
        voices = self._sync_client.voice_cloning.list_voices()
        return self._format_voices(voices)

    async def async_list_voices(self) -> str:
        """List all available voices from CAMB AI (async version).

        Returns:
            str: JSON array of voice objects.
        """
        voices = await self._async_client.voice_cloning.list_voices()
        return self._format_voices(voices)

    def _format_voices(self, voices) -> str:
        out = []
        for v in voices:
            if isinstance(v, dict):
                out.append({
                    "id": v.get("id"), "name": v.get("voice_name", v.get("name", "Unknown")),
                    "gender": self._gender_str(v.get("gender", 0)),
                    "age": v.get("age"), "language": v.get("language"),
                })
            else:
                out.append({
                    "id": getattr(v, "id", None),
                    "name": getattr(v, "voice_name", getattr(v, "name", "Unknown")),
                    "gender": self._gender_str(getattr(v, "gender", 0)),
                    "age": getattr(v, "age", None), "language": getattr(v, "language", None),
                })
        return json.dumps(out, indent=2)

    # ------------------------------------------------------------------
    # 7. Voice from Description
    # ------------------------------------------------------------------

    def create_voice_from_description(
        self,
        text: str,
        voice_description: str,
    ) -> str:
        """Generate a synthetic voice from a detailed text description using CAMB AI.

        Use this tool to create a new voice by describing its characteristics. Provide
        sample text the voice will speak and a detailed description of the desired voice
        (minimum 100 characters / 18+ words). Include details like accent, tone, age,
        gender, speaking style, etc. Returns preview audio URLs.

        Args:
            text: Sample text the generated voice will speak.
            voice_description: Detailed description of the desired voice (min 100 chars).

        Returns:
            str: JSON string with preview audio URLs for the generated voice.
        """
        result = self._sync_client.text_to_voice.create_text_to_voice(
            text=text, voice_description=voice_description,
        )
        status = self._poll_sync(self._sync_client.text_to_voice.get_text_to_voice_status, result.task_id)
        voice_result = self._sync_client.text_to_voice.get_text_to_voice_result(status.run_id)

        out = {
            "previews": getattr(voice_result, "previews", []),
            "status": "completed",
        }
        return json.dumps(out, indent=2)

    async def async_create_voice_from_description(
        self,
        text: str,
        voice_description: str,
    ) -> str:
        """Generate a synthetic voice from a text description using CAMB AI (async version).

        Args:
            text: Sample text the generated voice will speak.
            voice_description: Detailed description of the desired voice (min 100 chars).

        Returns:
            str: JSON string with preview audio URLs.
        """
        result = await self._async_client.text_to_voice.create_text_to_voice(
            text=text, voice_description=voice_description,
        )
        status = await self._poll_async(self._async_client.text_to_voice.get_text_to_voice_status, result.task_id)
        voice_result = await self._async_client.text_to_voice.get_text_to_voice_result(status.run_id)

        out = {
            "previews": getattr(voice_result, "previews", []),
            "status": "completed",
        }
        return json.dumps(out, indent=2)

    # ------------------------------------------------------------------
    # 8. Text-to-Sound
    # ------------------------------------------------------------------

    def text_to_sound(
        self,
        prompt: str,
        duration: Optional[float] = None,
        audio_type: Optional[str] = None,
    ) -> str:
        """Generate sounds, music, or soundscapes from text descriptions using CAMB AI.

        Use this tool to create audio from text descriptions. Describe the sound or music
        you want and the tool will generate it. Returns the file path to the audio.

        Args:
            prompt: Description of the sound or music to generate.
            duration: Optional duration in seconds.
            audio_type: Optional type: 'music' or 'sound'.

        Returns:
            str: File path to the generated audio file.
        """
        kwargs: Dict[str, Any] = {"prompt": prompt}
        if duration:
            kwargs["duration"] = duration
        if audio_type:
            kwargs["audio_type"] = audio_type

        result = self._sync_client.text_to_audio.create_text_to_audio(**kwargs)
        status = self._poll_sync(self._sync_client.text_to_audio.get_text_to_audio_status, result.task_id)

        chunks: list[bytes] = []
        for chunk in self._sync_client.text_to_audio.get_text_to_audio_result(status.run_id):
            chunks.append(chunk)
        return self._save_audio(b"".join(chunks), ".wav")

    async def async_text_to_sound(
        self,
        prompt: str,
        duration: Optional[float] = None,
        audio_type: Optional[str] = None,
    ) -> str:
        """Generate sounds or music from text descriptions using CAMB AI (async version).

        Args:
            prompt: Description of the sound or music.
            duration: Optional duration in seconds.
            audio_type: Optional type: 'music' or 'sound'.

        Returns:
            str: File path to the generated audio file.
        """
        kwargs: Dict[str, Any] = {"prompt": prompt}
        if duration:
            kwargs["duration"] = duration
        if audio_type:
            kwargs["audio_type"] = audio_type

        result = await self._async_client.text_to_audio.create_text_to_audio(**kwargs)
        status = await self._poll_async(self._async_client.text_to_audio.get_text_to_audio_status, result.task_id)

        chunks: list[bytes] = []
        async for chunk in self._async_client.text_to_audio.get_text_to_audio_result(status.run_id):
            chunks.append(chunk)
        return self._save_audio(b"".join(chunks), ".wav")

    # ------------------------------------------------------------------
    # 8. Audio Separation
    # ------------------------------------------------------------------

    def separate_audio(
        self,
        audio_url: Optional[str] = None,
        audio_file_path: Optional[str] = None,
    ) -> str:
        """Separate vocals/speech from background audio using CAMB AI.

        Use this tool to isolate vocals from background music or noise. Provide either
        an audio URL or a local file path. Returns JSON with paths to the separated
        vocals and background audio files.

        Args:
            audio_url: URL of the audio file to separate.
            audio_file_path: Local file path to the audio file.

        Returns:
            str: JSON string with 'vocals' and 'background' file paths or URLs.
        """
        kwargs: Dict[str, Any] = {}
        if audio_file_path:
            with open(audio_file_path, "rb") as f:
                kwargs["media_file"] = f
                result = self._sync_client.audio_separation.create_audio_separation(**kwargs)
        else:
            result = self._sync_client.audio_separation.create_audio_separation(**kwargs)

        status = self._poll_sync(self._sync_client.audio_separation.get_audio_separation_status, result.task_id)
        sep = self._sync_client.audio_separation.get_audio_separation_run_info(status.run_id)
        return self._format_separation(sep)

    async def async_separate_audio(
        self,
        audio_url: Optional[str] = None,
        audio_file_path: Optional[str] = None,
    ) -> str:
        """Separate vocals from background audio using CAMB AI (async version).

        Args:
            audio_url: URL of the audio file.
            audio_file_path: Local file path to the audio file.

        Returns:
            str: JSON string with separation results.
        """
        kwargs: Dict[str, Any] = {}
        if audio_file_path:
            with open(audio_file_path, "rb") as f:
                kwargs["media_file"] = f
                result = await self._async_client.audio_separation.create_audio_separation(**kwargs)
        else:
            result = await self._async_client.audio_separation.create_audio_separation(**kwargs)

        status = await self._poll_async(
            self._async_client.audio_separation.get_audio_separation_status, result.task_id
        )
        sep = await self._async_client.audio_separation.get_audio_separation_run_info(status.run_id)
        return self._format_separation(sep)

    def _format_separation(self, sep) -> str:
        out: Dict[str, Any] = {"vocals": None, "background": None, "status": "completed"}
        for attr, key in [
            ("vocals_url", "vocals"), ("vocals", "vocals"), ("voice_url", "vocals"),
            ("background_url", "background"), ("background", "background"), ("instrumental_url", "background"),
        ]:
            val = getattr(sep, attr, None)
            if val and out[key] is None:
                if isinstance(val, bytes):
                    out[key] = self._save_audio(val, f"_{key}.wav")
                else:
                    out[key] = val
        return json.dumps(out, indent=2)
