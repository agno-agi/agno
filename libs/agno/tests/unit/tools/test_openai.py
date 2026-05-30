from types import SimpleNamespace

from agno.tools import openai as openai_tools
from agno.tools.openai import OpenAITools


def test_transcribe_audio_closes_file(tmp_path, monkeypatch):
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"fake audio")

    class Transcriptions:
        opened_file = None

        def create(self, *, model, file, response_format):
            assert model == "whisper-1"
            assert response_format == "text"
            assert not file.closed
            self.opened_file = file
            return "transcript text"

    transcriptions = Transcriptions()

    class FakeOpenAIClient:
        def __init__(self, *, api_key):
            assert api_key == "test-key"
            self.audio = SimpleNamespace(transcriptions=transcriptions)

    monkeypatch.setattr(openai_tools, "OpenAIClient", FakeOpenAIClient)

    tools = OpenAITools(
        api_key="test-key",
        enable_image_generation=False,
        enable_speech_generation=False,
    )

    assert tools.transcribe_audio(str(audio_path)) == "transcript text"
    assert transcriptions.opened_file is not None
    assert transcriptions.opened_file.closed
