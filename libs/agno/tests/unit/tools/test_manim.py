import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("manim")

from agno.media import Video  # noqa: E402
from agno.tools.function import ToolResult  # noqa: E402
from agno.tools.manim import ManimTools  # noqa: E402

FAKE_MP4 = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 256


def _extract_cmd_args(cmd):
    """Pull --media_dir value and the trailing scene_name out of a manim cmd list."""
    media_dir = Path(cmd[cmd.index("--media_dir") + 1])
    scene_name = cmd[-1]
    return media_dir, scene_name


def _plant_mp4(media_dir: Path, scene_name: str, payload: bytes = FAKE_MP4) -> Path:
    """Write a fake mp4 under media_dir so _locate_mp4's glob fallback finds it."""
    videos_dir = media_dir / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    mp4_path = videos_dir / f"{scene_name}.mp4"
    mp4_path.write_bytes(payload)
    return mp4_path


def _manim_success_side_effect(payload: bytes = FAKE_MP4):
    """Build a subprocess.run side_effect that simulates a successful manim render."""

    def _run(cmd, *args, **kwargs):
        media_dir, scene_name = _extract_cmd_args(cmd)
        _plant_mp4(media_dir, scene_name, payload)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    return _run


def _make_tools(tmp_dir: Path, **overrides) -> ManimTools:
    return ManimTools(output_dir=tmp_dir, **overrides)


def test_invalid_quality_on_init():
    with tempfile.TemporaryDirectory() as tmp_dir:
        with pytest.raises(ValueError, match="quality must be one of"):
            ManimTools(output_dir=tmp_dir, quality="z")


def test_invalid_quality_on_render_returns_error():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = _make_tools(Path(tmp_dir))
        result = tools.render_scene(scene_code="", scene_name="S", quality="z")
        assert isinstance(result, ToolResult)
        assert "unknown quality" in result.content
        assert not result.videos


def test_invalid_max_duration_rejected():
    with tempfile.TemporaryDirectory() as tmp_dir:
        with pytest.raises(ValueError, match="max_duration_seconds"):
            ManimTools(output_dir=tmp_dir, max_duration_seconds=0)


def test_invalid_voice_service_rejected():
    with tempfile.TemporaryDirectory() as tmp_dir:
        with pytest.raises(ValueError, match="voice_service must be one of"):
            ManimTools(output_dir=tmp_dir, enable_voiceover=True, voice_service="bogus")


def test_invalid_max_inline_bytes_rejected():
    with tempfile.TemporaryDirectory() as tmp_dir:
        with pytest.raises(ValueError, match="max_inline_bytes"):
            ManimTools(output_dir=tmp_dir, max_inline_bytes=0)


def test_missing_executable_returns_error_and_cleans_up():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = _make_tools(Path(tmp_dir))
        with patch("agno.tools.manim.subprocess.run", side_effect=FileNotFoundError("no manim")):
            result = tools.render_scene(scene_code="x", scene_name="S")
        assert "not found" in result.content
        assert not result.videos
        assert not any(Path(tmp_dir).glob("S_*.py"))
        assert not any(Path(tmp_dir).glob("media_*"))


def test_render_timeout_returns_error_and_cleans_up():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = _make_tools(Path(tmp_dir), timeout_seconds=5)
        with patch(
            "agno.tools.manim.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="manim", timeout=5),
        ):
            result = tools.render_scene(scene_code="x", scene_name="S")
        assert "timed out" in result.content
        assert "5s" in result.content
        assert not result.videos
        assert not any(Path(tmp_dir).glob("S_*.py"))


def test_nonzero_exit_returns_stderr_tail():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = _make_tools(Path(tmp_dir))
        stderr = "\n".join(f"traceback line {i}" for i in range(50))
        fake_completed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)
        with patch("agno.tools.manim.subprocess.run", return_value=fake_completed):
            result = tools.render_scene(scene_code="x", scene_name="S")
        assert "Render failed" in result.content
        assert "returncode=1" in result.content
        assert "traceback line 49" in result.content
        assert "traceback line 0" not in result.content
        assert not result.videos


def test_success_but_no_mp4_returns_error():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = _make_tools(Path(tmp_dir))
        fake_completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch("agno.tools.manim.subprocess.run", return_value=fake_completed):
            result = tools.render_scene(scene_code="x", scene_name="S")
        assert "no mp4 was found" in result.content
        assert not result.videos


def test_happy_path_inline_delivery(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = _make_tools(Path(tmp_dir))
        monkeypatch.setattr(tools, "_probe_duration_seconds", lambda p: 5.0)
        with patch("agno.tools.manim.subprocess.run", side_effect=_manim_success_side_effect()):
            result = tools.render_scene(scene_code="x", scene_name="MyScene")
        assert isinstance(result, ToolResult)
        assert result.videos and len(result.videos) == 1
        video = result.videos[0]
        assert isinstance(video, Video)
        assert video.format == "mp4"
        assert video.mime_type == "video/mp4"
        assert video.content == FAKE_MP4
        assert video.filepath is None
        assert "base64-inlined" in result.content
        # Artifacts cleaned up
        assert not any(Path(tmp_dir).glob("MyScene_*.py"))
        assert not any(Path(tmp_dir).glob("media_*"))


def test_happy_path_filepath_over_cap(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = _make_tools(Path(tmp_dir), max_inline_bytes=32)
        monkeypatch.setattr(tools, "_probe_duration_seconds", lambda p: 5.0)
        big_payload = b"X" * 1024
        with patch(
            "agno.tools.manim.subprocess.run",
            side_effect=_manim_success_side_effect(payload=big_payload),
        ):
            result = tools.render_scene(scene_code="x", scene_name="BigScene")
        assert result.videos and len(result.videos) == 1
        video = result.videos[0]
        assert video.content is None
        assert video.filepath is not None
        persistent = Path(video.filepath)
        assert persistent.exists()
        assert persistent.read_bytes() == big_payload
        assert str(persistent.parent) == str(Path(tmp_dir).resolve())
        assert "inline cap" in result.content
        # media_dir gone but persisted mp4 remains under output_dir
        assert not any(Path(tmp_dir).glob("media_*"))


def test_duration_exceeded_rejects(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = _make_tools(Path(tmp_dir), max_duration_seconds=60)
        monkeypatch.setattr(tools, "_probe_duration_seconds", lambda p: 200.0)
        with patch("agno.tools.manim.subprocess.run", side_effect=_manim_success_side_effect()):
            result = tools.render_scene(scene_code="x", scene_name="TooLong")
        assert "duration 200.0s" in result.content
        assert "max_duration_seconds=60s" in result.content
        assert not result.videos
        # Artifacts cleaned
        assert not any(Path(tmp_dir).glob("TooLong_*.py"))
        assert not any(Path(tmp_dir).glob("media_*"))


def test_duration_probe_missing_warns_but_renders(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = _make_tools(Path(tmp_dir))
        monkeypatch.setattr(tools, "_probe_duration_seconds", lambda p: None)
        with patch("agno.tools.manim.subprocess.run", side_effect=_manim_success_side_effect()):
            result = tools.render_scene(scene_code="x", scene_name="NoProbe")
        assert result.videos and result.videos[0].content == FAKE_MP4


def test_delete_after_render_false_keeps_artifacts(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = _make_tools(Path(tmp_dir), delete_after_render=False)
        monkeypatch.setattr(tools, "_probe_duration_seconds", lambda p: 5.0)
        with patch("agno.tools.manim.subprocess.run", side_effect=_manim_success_side_effect()):
            result = tools.render_scene(scene_code="x", scene_name="Persist")
        assert result.videos
        assert any(Path(tmp_dir).glob("Persist_*.py"))
        assert any(Path(tmp_dir).glob("media_*"))


def test_async_variant_matches_sync(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = _make_tools(Path(tmp_dir))
        monkeypatch.setattr(tools, "_probe_duration_seconds", lambda p: 5.0)
        with patch("agno.tools.manim.subprocess.run", side_effect=_manim_success_side_effect()):
            result = asyncio.run(tools.arender_scene(scene_code="x", scene_name="AsyncScene"))
        assert isinstance(result, ToolResult)
        assert result.videos and result.videos[0].content == FAKE_MP4


def test_list_rendered_videos_empty_then_populated(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = _make_tools(Path(tmp_dir))
        assert "No videos" in tools.list_rendered_videos()
        monkeypatch.setattr(tools, "_probe_duration_seconds", lambda p: 4.2)
        with patch("agno.tools.manim.subprocess.run", side_effect=_manim_success_side_effect()):
            tools.render_scene(scene_code="x", scene_name="Listed")
        records = json.loads(tools.list_rendered_videos())
        assert len(records) == 1
        record = records[0]
        assert record["scene_name"] == "Listed"
        assert record["quality"] == "m"
        assert record["delivery"] == "inline"
        assert record["duration_seconds"] == 4.2
        assert record["size_mb"] >= 0


def test_build_cmd_includes_log_flags():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tools = _make_tools(Path(tmp_dir))
        cmd = tools._build_cmd(Path("scene.py"), "S", "m", Path("media"))
        assert "-v" in cmd and cmd[cmd.index("-v") + 1] == "WARNING"
        assert "--progress_bar" in cmd and cmd[cmd.index("--progress_bar") + 1] == "none"
        assert "-qm" in cmd
