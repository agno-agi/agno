"""
MLX Transcribe Tools - Audio Transcription using Apple's MLX Framework

Requirements:
    - ffmpeg: Required for audio processing
        macOS: brew install ffmpeg
        Ubuntu: apt-get install ffmpeg
        Windows: Download from https://ffmpeg.org/download.html

    - mlx-whisper: Install via pip
        pip install mlx-whisper

This module provides tools for transcribing audio files using the MLX Whisper model,
optimized for Apple Silicon processors. It supports various audio formats and
provides high-quality transcription capabilities.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    import mlx_whisper
except ImportError:
    raise ImportError("`mlx_whisper` not installed. Please install using `pip install mlx-whisper`")


class MLXTranscribeTools(Toolkit):
    def __init__(
        self,
        base_dir: Optional[Path] = None,
        read_files_in_base_dir: bool = True,
        path_or_hf_repo: str = "mlx-community/whisper-large-v3-turbo",
        verbose: Optional[bool] = None,
        temperature: Optional[Union[float, Tuple[float, ...]]] = None,
        compression_ratio_threshold: Optional[float] = None,
        logprob_threshold: Optional[float] = None,
        no_speech_threshold: Optional[float] = None,
        condition_on_previous_text: Optional[bool] = None,
        initial_prompt: Optional[str] = None,
        word_timestamps: Optional[bool] = None,
        prepend_punctuations: Optional[str] = None,
        append_punctuations: Optional[str] = None,
        clip_timestamps: Optional[Union[str, List[float]]] = None,
        hallucination_silence_threshold: Optional[float] = None,
        decode_options: Optional[dict] = None,
    ):
        super().__init__(name="mlx_transcribe")

        self.base_dir: Path = base_dir or Path.cwd()
        self.path_or_hf_repo: str = path_or_hf_repo
        self.verbose: Optional[bool] = verbose
        self.temperature: Optional[Union[float, Tuple[float, ...]]] = temperature
        self.compression_ratio_threshold: Optional[float] = compression_ratio_threshold
        self.logprob_threshold: Optional[float] = logprob_threshold
        self.no_speech_threshold: Optional[float] = no_speech_threshold
        self.condition_on_previous_text: Optional[bool] = condition_on_previous_text
        self.initial_prompt: Optional[str] = initial_prompt
        self.word_timestamps: Optional[bool] = word_timestamps
        self.prepend_punctuations: Optional[str] = prepend_punctuations
        self.append_punctuations: Optional[str] = append_punctuations
        self.clip_timestamps: Optional[Union[str, List[float]]] = clip_timestamps
        self.hallucination_silence_threshold: Optional[float] = hallucination_silence_threshold
        self.decode_options: Optional[dict] = decode_options

        self.register(self.transcribe)
        if read_files_in_base_dir:
            self.register(self.read_files)

    def transcribe(self, file_name: str) -> str:
        """
        Transcribe uses Apple's MLX Whisper model.

        Args:
            file_name (str): The name of the audio file to transcribe.

        Returns:
            str: The transcribed text or an error message if the transcription fails.
        """
        try:
            audio_file_path = str(self.base_dir.joinpath(file_name))
            if audio_file_path is None:
                return "No audio file path provided"

            logger.info(f"Transcribing audio file {audio_file_path}")
            transcription_kwargs: Dict[str, Any] = {
                "path_or_hf_repo": self.path_or_hf_repo,
            }
            if self.verbose is not None:
                transcription_kwargs["verbose"] = self.verbose
            if self.temperature is not None:
                transcription_kwargs["temperature"] = self.temperature
            if self.compression_ratio_threshold is not None:
                transcription_kwargs["compression_ratio_threshold"] = self.compression_ratio_threshold
            if self.logprob_threshold is not None:
                transcription_kwargs["logprob_threshold"] = self.logprob_threshold
            if self.no_speech_threshold is not None:
                transcription_kwargs["no_speech_threshold"] = self.no_speech_threshold
            if self.condition_on_previous_text is not None:
                transcription_kwargs["condition_on_previous_text"] = self.condition_on_previous_text
            if self.initial_prompt is not None:
                transcription_kwargs["initial_prompt"] = self.initial_prompt
            if self.word_timestamps is not None:
                transcription_kwargs["word_timestamps"] = self.word_timestamps
            if self.prepend_punctuations is not None:
                transcription_kwargs["prepend_punctuations"] = self.prepend_punctuations
            if self.append_punctuations is not None:
                transcription_kwargs["append_punctuations"] = self.append_punctuations
            if self.clip_timestamps is not None:
                transcription_kwargs["clip_timestamps"] = self.clip_timestamps
            if self.hallucination_silence_threshold is not None:
                transcription_kwargs["hallucination_silence_threshold"] = self.hallucination_silence_threshold
            if self.decode_options is not None:
                transcription_kwargs.update(self.decode_options)

            transcription = mlx_whisper.transcribe(audio_file_path, **transcription_kwargs)
            return transcription.get("text", "")
        except Exception as e:
            _e = f"Failed to transcribe audio file {e}"
            logger.error(_e)
            return _e

    def read_files(self) -> str:
        """Returns a list of files in the base directory

        Returns:
            str: A JSON string containing the list of files in the base directory.
        """
        try:
            logger.info(f"Reading files in : {self.base_dir}")
            return json.dumps([str(file_name) for file_name in self.base_dir.iterdir()], indent=4)
        except Exception as e:
            logger.error(f"Error reading files: {e}")
            return f"Error reading files: {e}"
