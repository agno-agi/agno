import importlib
import sys
import types

import pytest


@pytest.fixture()
def moviepy_video_module(monkeypatch):
    fake_moviepy = types.ModuleType("moviepy")

    class FakeClip:
        pass

    fake_moviepy.ColorClip = FakeClip
    fake_moviepy.CompositeVideoClip = FakeClip
    fake_moviepy.TextClip = FakeClip
    fake_moviepy.VideoFileClip = FakeClip

    monkeypatch.setitem(sys.modules, "moviepy", fake_moviepy)
    sys.modules.pop("agno.tools.moviepy_video", None)
    module = importlib.import_module("agno.tools.moviepy_video")
    yield module
    sys.modules.pop("agno.tools.moviepy_video", None)


def test_create_srt_cleans_temp_file_when_replace_fails(moviepy_video_module, monkeypatch, tmp_path):
    output_path = tmp_path / "captions.srt"
    output_path.write_text("existing", encoding="utf-8")

    def fail_replace(src: str, dst: str) -> None:
        raise RuntimeError("replace failed")

    monkeypatch.setattr(moviepy_video_module.os, "replace", fail_replace)

    tools = moviepy_video_module.MoviePyVideoTools(enable_process_video=False, enable_embed_captions=False)
    result = tools.create_srt("new subtitles", str(output_path))

    assert result == "Failed to create SRT file: replace failed"
    assert output_path.read_text(encoding="utf-8") == "existing"
    assert list(tmp_path.glob(".*.tmp.srt")) == []


def test_create_srt_replaces_output_after_successful_temp_write(moviepy_video_module, tmp_path):
    output_path = tmp_path / "captions.srt"

    tools = moviepy_video_module.MoviePyVideoTools(enable_process_video=False, enable_embed_captions=False)
    result = tools.create_srt("new subtitles", str(output_path))

    assert result == str(output_path)
    assert output_path.read_text(encoding="utf-8") == "new subtitles"
    assert list(tmp_path.glob(".*.tmp.srt")) == []


def test_embed_captions_cleans_temp_video_when_render_fails(moviepy_video_module, monkeypatch, tmp_path):
    video_path = tmp_path / "input.mp4"
    srt_path = tmp_path / "captions.srt"
    output_path = tmp_path / "output.mp4"
    video_path.write_text("input video", encoding="utf-8")
    srt_path.write_text("", encoding="utf-8")
    output_path.write_text("existing video", encoding="utf-8")

    closed = []

    class FakeVideo:
        h = 100
        w = 200
        fps = 30
        size = (200, 100)

        def close(self):
            closed.append("video")

    class FailingFinalVideo:
        def __init__(self, clips, size):
            self.clips = clips
            self.size = size

        def write_videofile(self, path: str, **kwargs):
            with open(path, "w", encoding="utf-8") as f:
                f.write("partial video")
            raise RuntimeError("render failed")

        def close(self):
            closed.append("final")

    monkeypatch.setattr(moviepy_video_module, "VideoFileClip", lambda path: FakeVideo())
    monkeypatch.setattr(moviepy_video_module, "CompositeVideoClip", FailingFinalVideo)

    tools = moviepy_video_module.MoviePyVideoTools(enable_process_video=False, enable_generate_captions=False)
    result = tools.embed_captions(str(video_path), str(srt_path), str(output_path))

    assert result == "Failed to embed captions: render failed"
    assert output_path.read_text(encoding="utf-8") == "existing video"
    assert list(tmp_path.glob(".*.tmp.mp4")) == []
    assert closed == ["final", "video"]
