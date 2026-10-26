"""Render Manim Community Edition scenes and attach the resulting mp4 to the run response.

Requires `manim` and `ffmpeg` on the system (ffprobe is used for the duration
check). LaTeX is optional (only needed if your scenes use `MathTex` / `Tex`).

Renders under `max_inline_bytes` (default 25 MB) come back as
`Video(content=bytes)` and are base64-inlined at serialization time so any
consumer of `RunOutput.videos` receives a self-contained video. Larger
renders are persisted under `output_dir` and returned as
`Video(filepath=...)` to avoid blowing up the SSE payload.

Renders longer than `max_duration_seconds` (default 120 s) are rejected
with an error so the agent can shorten the scene and retry.

By default each render's scene `.py` and its `media_{run_id}/` subtree are
deleted once the mp4 has been handled. Pass `delete_after_render=False`
if you want to inspect the render artifacts on disk.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Union

from agno.media import Video
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_info, log_warning

try:
    import manim  # type: ignore  # noqa: F401
except ImportError:
    raise ImportError("`manim` not installed. Please install using `pip install manim`")

QUALITY_MAP = {
    "l": ("ql", "480p15"),
    "m": ("qm", "720p30"),
    "h": ("qh", "1080p60"),
    "k": ("qk", "2160p60"),
}

_VOICE_SERVICES: Dict[str, Dict[str, str]] = {
    "gtts": {
        "class_name": "GTTSService",
        "import_path": "manim_voiceover.services.gtts",
        "install_extra": "gtts",
        "usage_hint": (
            "GTTSService() takes no args for defaults; use "
            "GTTSService(lang='en', tld='com') to override. Free, no API key."
        ),
    },
    "elevenlabs": {
        "class_name": "ElevenLabsService",
        "import_path": "manim_voiceover.services.elevenlabs",
        "install_extra": "elevenlabs",
        "usage_hint": (
            "ElevenLabsService(voice_id='21m00Tcm4TlvDq8ikWAM', transcription_model=None) "
            "is the recommended default. Use voice_id (not voice_name) for predictable "
            "results: voice_name does an exact-string match against the user's ENTIRE "
            "ElevenLabs library (including cloned voices), so name collisions can pick "
            "the wrong voice. '21m00Tcm4TlvDq8ikWAM' is canonical female Rachel. Other "
            "safe IDs: 'EXAVITQu4vr4xnSDxMaL' (Bella, soft), 'XB0fDUnXU5powFXDhCwa' "
            "(Charlotte, British). transcription_model=None skips local Whisper "
            "(unnecessary for run_time=tracker.duration sync; adds 2-10s per chunk "
            "otherwise). Pass model='eleven_multilingual_v2' for multilingual output. "
            "Requires ELEVEN_API_KEY env var."
        ),
    },
    "openai": {
        "class_name": "OpenAIService",
        "import_path": "manim_voiceover.services.openai",
        "install_extra": "openai",
        "usage_hint": (
            "OpenAIService(voice='nova', model='tts-1-hd', transcription_model=None) "
            "is the recommended default. transcription_model=None is CRITICAL: the "
            "service defaults it to 'base', which runs local Whisper on every clip "
            "(adds 2-10s per chunk and is only needed for word-level "
            "tracker.time_until_bookmark sync - whole-clip run_time=tracker.duration "
            "does NOT need it). Voices: 'alloy', 'echo', 'fable', 'onyx', 'nova', "
            "'shimmer' (no library collisions - all are canonical). Models: 'tts-1' "
            "(faster) or 'tts-1-hd' (higher quality). Requires OPENAI_API_KEY env var."
        ),
    },
}


def _build_voiceover_instructions(service_name: str) -> str:
    svc = _VOICE_SERVICES[service_name]
    return (
        f"Voiceovers are available via `manim_voiceover`. "
        f"Subclass `VoiceoverScene` instead of `Scene`, import "
        f"`{svc['class_name']}` from `{svc['import_path']}`, call "
        f"`self.set_speech_service({svc['class_name']}(...))` at the top of "
        f"`construct`, and wrap each animation in "
        f"`with self.voiceover(text=...) as tracker:` using "
        f"`run_time=tracker.duration` so animations sync to the narration. "
        f"{svc['usage_hint']}"
    )


class ManimTools(Toolkit):
    def __init__(
        self,
        output_dir: Union[Path, str],
        timeout_seconds: int = 900,
        max_duration_seconds: float = 120.0,
        max_inline_bytes: int = 25 * 1024 * 1024,
        quality: str = "m",
        python_executable: Optional[str] = None,
        delete_after_render: bool = True,
        enable_voiceover: bool = False,
        voice_service: str = "gtts",
        enable_render_scene: bool = True,
        enable_list_rendered_videos: bool = True,
        all: bool = False,
        **kwargs,
    ):
        if quality not in QUALITY_MAP:
            raise ValueError(f"quality must be one of {list(QUALITY_MAP.keys())}, got {quality!r}")
        if max_duration_seconds <= 0:
            raise ValueError(f"max_duration_seconds must be > 0, got {max_duration_seconds!r}")
        if max_inline_bytes <= 0:
            raise ValueError(f"max_inline_bytes must be > 0, got {max_inline_bytes!r}")

        if enable_voiceover:
            if voice_service not in _VOICE_SERVICES:
                raise ValueError(f"voice_service must be one of {list(_VOICE_SERVICES)}, got {voice_service!r}")
            svc = _VOICE_SERVICES[voice_service]
            try:
                import manim_voiceover  # type: ignore  # noqa: F401
            except ImportError:
                raise ImportError(
                    "`manim_voiceover` is required when enable_voiceover=True. "
                    f'Install with `pip install "manim-voiceover[{svc["install_extra"]}]"` '
                    "(swap the extra for a different service: gtts, openai, azure, elevenlabs, coqui, recorder)."
                )
            try:
                importlib.import_module(svc["import_path"])
            except ImportError as e:
                raise ImportError(
                    f"`{svc['class_name']}` is not available. Install with "
                    f'`pip install "manim-voiceover[{svc["install_extra"]}]"`. '
                    f"Underlying error: {e}"
                )
            if shutil.which("sox") is None:
                log_warning(
                    "SoX is not on PATH. manim_voiceover uses SoX to trim silence and "
                    "normalize audio - voiceover renders will still run but audio quality "
                    "will be degraded. Install SoX: "
                    "`winget install ChrisBagwell.SoX` (Windows), "
                    "`brew install sox` (macOS), or "
                    "`sudo apt install sox` (Debian/Ubuntu)."
                )

        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = timeout_seconds
        self.max_duration_seconds = max_duration_seconds
        self.max_inline_bytes = max_inline_bytes
        self.default_quality = quality
        self.python_executable = python_executable or sys.executable
        self.delete_after_render = delete_after_render
        self.voiceover_enabled = enable_voiceover
        self.voice_service = voice_service if enable_voiceover else None
        self._rendered: List[dict] = []

        tools: List = []
        async_tools: List = []
        if all or enable_render_scene:
            tools.append(self.render_scene)
            async_tools.append((self.arender_scene, "arender_scene"))
        if all or enable_list_rendered_videos:
            tools.append(self.list_rendered_videos)

        super().__init__(
            name="manim_tools",
            tools=tools,
            async_tools=async_tools,
            instructions=_build_voiceover_instructions(voice_service) if enable_voiceover else None,
            add_instructions=enable_voiceover,
            **kwargs,
        )

    def _build_cmd(self, scene_file: Path, scene_name: str, quality: str, media_dir: Path) -> List[str]:
        flag, _ = QUALITY_MAP[quality]
        return [
            self.python_executable,
            "-m",
            "manim",
            f"-{flag}",
            "-v",
            "WARNING",
            "--progress_bar",
            "none",
            "--format",
            "mp4",
            "--media_dir",
            str(media_dir),
            str(scene_file),
            scene_name,
        ]

    def _probe_duration_seconds(self, mp4_path: Path) -> Optional[float]:
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(mp4_path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except (subprocess.SubprocessError, ValueError, FileNotFoundError):
            pass
        return None

    def _locate_mp4(self, scene_file: Path, scene_name: str, quality: str, media_dir: Path) -> Optional[Path]:
        _, qfolder = QUALITY_MAP[quality]
        expected = media_dir / "videos" / scene_file.stem / qfolder / f"{scene_name}.mp4"
        if expected.exists():
            return expected
        matches = list(media_dir.glob(f"**/{scene_name}.mp4"))
        return matches[0] if matches else None

    def _cleanup(self, scene_file: Path, media_dir: Path) -> None:
        if not self.delete_after_render:
            return
        try:
            scene_file.unlink(missing_ok=True)
        except OSError:
            pass
        shutil.rmtree(media_dir, ignore_errors=True)

    def render_scene(
        self,
        scene_code: str,
        scene_name: str,
        quality: Optional[str] = None,
    ) -> ToolResult:
        """Render a Manim Community Edition scene and attach the mp4 to the response.

        Args:
            scene_code (str): Full Python source for the scene. Must include
                `from manim import *` (or equivalent imports) and a class named
                exactly `scene_name` that subclasses `Scene` / `ThreeDScene` /
                `VoiceoverScene`.
            scene_name (str): Class name of the scene to render. Must match the
                class defined in `scene_code` and be importable as-is.
            quality (str, optional): Render quality: 'l' (480p15), 'm' (720p30),
                'h' (1080p60), 'k' (2160p60). Defaults to the toolkit's configured
                default quality.

        Returns:
            ToolResult: On success, contains a human-readable summary and the
                rendered Video attached via `videos=[...]`. On failure, contains
                only an error message in `content` and no video.
        """
        q = quality or self.default_quality
        if q not in QUALITY_MAP:
            return ToolResult(content=f"Error: unknown quality '{q}'. Must be one of {list(QUALITY_MAP.keys())}.")

        run_id = uuid.uuid4().hex[:8]
        scene_file = self.output_dir / f"{scene_name}_{run_id}.py"
        media_dir = self.output_dir / f"media_{run_id}"

        try:
            scene_file.write_text(scene_code, encoding="utf-8")
        except OSError as e:
            return ToolResult(content=f"Error writing scene file: {e}")

        cmd = self._build_cmd(scene_file, scene_name, q, media_dir)
        log_info(f"Rendering manim scene: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            self._cleanup(scene_file, media_dir)
            return ToolResult(
                content=f"Error: render timed out after {self.timeout_seconds}s for scene '{scene_name}'."
            )
        except FileNotFoundError as e:
            self._cleanup(scene_file, media_dir)
            return ToolResult(content=f"Error: Python executable or manim not found: {e}")

        if result.returncode != 0:
            tail = "\n".join(result.stderr.splitlines()[-30:])
            log_warning(f"Manim render failed for {scene_name}: {tail}")
            self._cleanup(scene_file, media_dir)
            return ToolResult(
                content=(
                    f"Render failed for scene '{scene_name}' (returncode={result.returncode}).\n\nstderr tail:\n{tail}"
                )
            )

        mp4_path = self._locate_mp4(scene_file, scene_name, q, media_dir)
        if mp4_path is None:
            self._cleanup(scene_file, media_dir)
            return ToolResult(
                content=f"Render reported success for '{scene_name}' but no mp4 was found under {media_dir}."
            )

        duration_seconds = self._probe_duration_seconds(mp4_path)
        if duration_seconds is None:
            log_warning(
                f"Could not probe duration for '{scene_name}' (ffprobe missing or failed); "
                f"skipping max_duration_seconds check."
            )
        elif duration_seconds > self.max_duration_seconds:
            self._cleanup(scene_file, media_dir)
            return ToolResult(
                content=(
                    f"Render rejected for '{scene_name}': duration {duration_seconds:.1f}s "
                    f"exceeds max_duration_seconds={self.max_duration_seconds:.0f}s. "
                    f"Shorten the scene (fewer animations, smaller self.wait() calls, or "
                    f"reduced voiceover length) and retry."
                )
            )

        size_bytes = mp4_path.stat().st_size
        size_mb = size_bytes / (1024 * 1024)

        record: dict = {
            "scene_name": scene_name,
            "quality": q,
            "size_mb": round(size_mb, 2),
        }
        if duration_seconds is not None:
            record["duration_seconds"] = round(duration_seconds, 2)

        if size_bytes <= self.max_inline_bytes:
            mp4_bytes = mp4_path.read_bytes()
            if not self.delete_after_render:
                record["filepath"] = str(mp4_path)
            record["delivery"] = "inline"
            self._rendered.append(record)
            self._cleanup(scene_file, media_dir)
            video = Video(content=mp4_bytes, format="mp4", mime_type="video/mp4")
            return ToolResult(
                content=(
                    f"Rendered '{scene_name}' at quality '{q}' ({size_mb:.2f} MB). "
                    f"The video is base64-inlined and attached to this response."
                ),
                videos=[video],
            )

        cap_mb = self.max_inline_bytes / (1024 * 1024)
        log_warning(
            f"Rendered mp4 is {size_mb:.1f} MB (> {cap_mb:.0f} MB cap); "
            f"returning filepath reference instead of inlined bytes."
        )
        persistent_path = self.output_dir / f"{scene_name}_{run_id}.mp4"
        shutil.move(str(mp4_path), str(persistent_path))
        shutil.rmtree(media_dir, ignore_errors=True)
        if self.delete_after_render:
            try:
                scene_file.unlink(missing_ok=True)
            except OSError:
                pass
        record["filepath"] = str(persistent_path)
        record["delivery"] = "filepath"
        self._rendered.append(record)
        video = Video(filepath=persistent_path, format="mp4", mime_type="video/mp4")
        return ToolResult(
            content=(
                f"Rendered '{scene_name}' at quality '{q}' ({size_mb:.2f} MB). "
                f"Exceeded the {cap_mb:.0f} MB inline cap; video is attached by filepath "
                f"at {persistent_path}."
            ),
            videos=[video],
        )

    async def arender_scene(
        self,
        scene_code: str,
        scene_name: str,
        quality: Optional[str] = None,
    ) -> ToolResult:
        """Async variant of render_scene. See render_scene for argument docs."""
        return await asyncio.to_thread(self.render_scene, scene_code, scene_name, quality)

    def list_rendered_videos(self) -> str:
        """List videos rendered in this session.

        Returns:
            str: JSON-encoded list of render records (scene_name, quality,
                size_mb, and filepath when `delete_after_render=False`), or
                a plain-text note if no renders have happened yet.
        """
        if not self._rendered:
            return "No videos have been rendered in this session yet."
        return json.dumps(self._rendered, indent=2)
