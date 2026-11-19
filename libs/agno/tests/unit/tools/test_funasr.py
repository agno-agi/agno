"""Unit tests for FunASRTools class.

funasr is an optional, heavy dependency (pulls torch); it is mocked here so these
tests run without it installed (as in CI). Only the toolkit wiring and the
transcribe/read_files logic are under test, not the real model.
"""

import sys
import types
from unittest.mock import MagicMock, patch

# Inject a lightweight fake `funasr` so the module-level import in
# agno.tools.funasr succeeds without the real (torch-heavy) package.
_funasr = types.ModuleType("funasr")
_funasr.AutoModel = MagicMock()
sys.modules.setdefault("funasr", _funasr)
_utils = types.ModuleType("funasr.utils")
sys.modules.setdefault("funasr.utils", _utils)
_pp = types.ModuleType("funasr.utils.postprocess_utils")
_pp.rich_transcription_postprocess = lambda text: text
sys.modules.setdefault("funasr.utils.postprocess_utils", _pp)

from agno.tools.funasr import FunASRTools  # noqa: E402


def test_init_defaults(tmp_path):
    tools = FunASRTools(base_dir=tmp_path)
    assert tools.name == "funasr"
    assert tools.model_id == "iic/SenseVoiceSmall"
    assert tools.device == "cpu"
    assert tools.language == "auto"
    assert tools.use_itn is True
    assert "transcribe" in tools.functions
    assert "read_files" in tools.functions


def test_init_custom_params(tmp_path):
    tools = FunASRTools(
        base_dir=tmp_path,
        model="iic/speech_paraformer-large",
        device="cuda",
        language="zh",
        use_itn=False,
        enable_read_files_in_base_dir=False,
    )
    assert tools.model_id == "iic/speech_paraformer-large"
    assert tools.device == "cuda"
    assert tools.language == "zh"
    assert tools.use_itn is False
    assert "transcribe" in tools.functions
    assert "read_files" not in tools.functions


def test_model_is_lazy(tmp_path):
    """The model must not be constructed until first use."""
    tools = FunASRTools(base_dir=tmp_path)
    assert tools._model is None


def test_transcribe_returns_clean_text(tmp_path):
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"RIFF....fake-wav....")

    tools = FunASRTools(base_dir=tmp_path)
    mock_model = MagicMock()
    mock_model.generate.return_value = [{"text": "<|zh|><|NEUTRAL|><|Speech|><|withitn|>hello world"}]

    with (
        patch.object(tools, "_get_model", return_value=mock_model),
        patch("agno.tools.funasr.rich_transcription_postprocess", return_value="hello world"),
    ):
        result = tools.transcribe("sample.wav")

    assert result == "hello world"
    mock_model.generate.assert_called_once()
    assert mock_model.generate.call_args.kwargs["language"] == "auto"
    assert mock_model.generate.call_args.kwargs["use_itn"] is True


def test_transcribe_file_not_found(tmp_path):
    tools = FunASRTools(base_dir=tmp_path)
    result = tools.transcribe("does_not_exist.wav")
    assert "not found" in result.lower()


def test_transcribe_path_outside_base_dir(tmp_path):
    tools = FunASRTools(base_dir=tmp_path, restrict_to_base_dir=True)
    result = tools.transcribe("../../etc/passwd")
    assert "Error" in result


def test_read_files_lists_audio(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"x")
    (tmp_path / "b.mp3").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("ignore me")

    tools = FunASRTools(base_dir=tmp_path)
    listing = tools.read_files()
    assert "a.wav" in listing
    assert "b.mp3" in listing
    assert "notes.txt" not in listing


def test_read_files_empty(tmp_path):
    tools = FunASRTools(base_dir=tmp_path)
    assert tools.read_files() == "No audio files found"
