"""
FunASR Tools - Audio transcription using FunASR (SenseVoice / Paraformer / Fun-ASR-Nano)

Requirements:
    - funasr: install via `pip install funasr`

FunASR (https://github.com/modelscope/FunASR) is an open-source speech toolkit with
strong multilingual ASR - Chinese, Cantonese, English, Japanese, Korean and more.
The model runs locally (CPU or CUDA); no API key is required. SenseVoice (the default
model) auto-detects the spoken language, and a built-in FSMN-VAD handles long audio.
"""

from pathlib import Path
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info

try:
    from funasr import AutoModel
    from funasr.utils.postprocess_utils import rich_transcription_postprocess
except ImportError:
    raise ImportError("`funasr` not installed. Please install using `pip install funasr`")


class FunASRTools(Toolkit):
    def __init__(
        self,
        base_dir: Optional[Path] = None,
        model: str = "iic/SenseVoiceSmall",
        device: str = "cpu",
        language: str = "auto",
        use_itn: bool = True,
        enable_read_files_in_base_dir: bool = True,
        restrict_to_base_dir: bool = True,
        **kwargs,
    ):
        self.base_dir: Path = (base_dir or Path.cwd()).resolve()
        self.restrict_to_base_dir = restrict_to_base_dir
        self.model_id: str = model
        self.device: str = device
        self.language: str = language
        self.use_itn: bool = use_itn
        self._model: Optional[Any] = None

        tools: List[Any] = [self.transcribe]
        if enable_read_files_in_base_dir:
            tools.append(self.read_files)
        super().__init__(name="funasr", tools=tools, **kwargs)

    def _get_model(self) -> Any:
        if self._model is None:
            log_info(f"Loading FunASR model '{self.model_id}' on {self.device}")
            self._model = AutoModel(
                model=self.model_id,
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 30000},
                device=self.device,
                disable_update=True,
            )
        return self._model

    def transcribe(self, file_name: str) -> str:
        """Transcribe a local audio file to text using FunASR.

        Args:
            file_name (str): The name of the audio file (within the base directory) to transcribe.

        Returns:
            str: The transcribed text, or an error message if transcription fails.
        """
        try:
            safe, file_path = self._check_path(file_name, self.base_dir, self.restrict_to_base_dir)
            if not safe:
                return f"Error: Path '{file_name}' is outside the allowed base directory"
            if not Path(file_path).exists():
                return f"Error: File '{file_name}' not found"

            log_info(f"Transcribing audio file {file_path} with FunASR")
            result = self._get_model().generate(
                input=str(file_path),
                cache={},
                language=self.language,
                use_itn=self.use_itn,
            )
            text = result[0]["text"] if result else ""
            return rich_transcription_postprocess(text).strip()
        except Exception as e:
            log_error(f"Failed to transcribe {file_name}: {e}")
            return f"Error transcribing {file_name}: {e}"

    def read_files(self) -> str:
        """List the audio files available in the base directory.

        Returns:
            str: A newline-separated list of audio file names, or a message if none are found.
        """
        try:
            audio_exts = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".opus", ".aac", ".mp4"}
            files = [p.name for p in self.base_dir.iterdir() if p.suffix.lower() in audio_exts]
            return "\n".join(sorted(files)) if files else "No audio files found"
        except Exception as e:
            log_error(f"Failed to list files in {self.base_dir}: {e}")
            return f"Error listing files: {e}"
