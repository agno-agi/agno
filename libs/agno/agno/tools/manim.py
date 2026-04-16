"""Render Manim Community Edition scenes and attach the resulting mp4 to the run response.

Requires `manim` and `ffmpeg` on the system. LaTeX is optional (only needed if
your scenes use `MathTex` / `Tex`).

The rendered mp4 is read into memory and attached as `Video(content=bytes)`.
At serialization time Agno base64-encodes `content`, so any consumer of
`RunOutput.videos` (AgentOS UI, Slack/WhatsApp interfaces, etc.) receives a
self-contained, inlined video - no static file route required.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import List, Optional, Union

from agno.media import Video
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_info, log_warning

QUALITY_MAP = {
    "l": ("ql", "480p15"),
    "m": ("qm", "720p30"),
    "h": ("qh", "1080p60"),
    "k": ("qk", "2160p60"),
}


class ManimTools(Toolkit):
    def __init__(
        self,
        output_dir: Union[Path, str],
        timeout_seconds: int = 180,
        quality: str = "m",
        python_executable: Optional[str] = None,
        enable_render_scene: bool = True,
        enable_list_rendered_videos: bool = True,
        all: bool = False,
        **kwargs,
    ):
        if quality not in QUALITY_MAP:
            raise ValueError(f"quality must be one of {list(QUALITY_MAP.keys())}, got {quality!r}")

        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = timeout_seconds
        self.default_quality = quality
        self.python_executable = python_executable or sys.executable
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
            **kwargs,
        )

    def _build_cmd(self, scene_file: Path, scene_name: str, quality: str, media_dir: Path) -> List[str]:
        flag, _ = QUALITY_MAP[quality]
        return [
            self.python_executable,
            "-m",
            "manim",
            f"-{flag}",
            "--format",
            "mp4",
            "--media_dir",
            str(media_dir),
            str(scene_file),
            scene_name,
        ]

    def _locate_mp4(self, scene_file: Path, scene_name: str, quality: str, media_dir: Path) -> Optional[Path]:
        _, qfolder = QUALITY_MAP[quality]
        expected = media_dir / "videos" / scene_file.stem / qfolder / f"{scene_name}.mp4"
        if expected.exists():
            return expected
        matches = list(media_dir.glob(f"**/{scene_name}.mp4"))
        return matches[0] if matches else None

    def _build_video(self, mp4_path: Path) -> Video:
        return Video(
            content=mp4_path.read_bytes(),
            format="mp4",
            mime_type="video/mp4",
        )

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
                exactly `scene_name` that subclasses `Scene` / `ThreeDScene` / etc.
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
            return ToolResult(
                content=f"Error: render timed out after {self.timeout_seconds}s for scene '{scene_name}'."
            )
        except FileNotFoundError as e:
            return ToolResult(content=f"Error: Python executable or manim not found: {e}")

        if result.returncode != 0:
            tail = "\n".join(result.stderr.splitlines()[-30:])
            log_warning(f"Manim render failed for {scene_name}: {tail}")
            return ToolResult(
                content=(
                    f"Render failed for scene '{scene_name}' (returncode={result.returncode}).\n\nstderr tail:\n{tail}"
                )
            )

        mp4_path = self._locate_mp4(scene_file, scene_name, q, media_dir)
        if mp4_path is None:
            return ToolResult(
                content=f"Render reported success for '{scene_name}' but no mp4 was found under {media_dir}."
            )

        video = self._build_video(mp4_path)
        size_mb = mp4_path.stat().st_size / (1024 * 1024)

        self._rendered.append(
            {
                "scene_name": scene_name,
                "quality": q,
                "filepath": str(mp4_path),
                "size_mb": round(size_mb, 2),
            }
        )

        return ToolResult(
            content=(
                f"Rendered '{scene_name}' at quality '{q}' ({size_mb:.2f} MB). "
                f"The video is base64-inlined and attached to this response."
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
                filepath, size_mb, delivery), or a plain-text note if no
                renders have happened yet.
        """
        if not self._rendered:
            return "No videos have been rendered in this session yet."
        return json.dumps(self._rendered, indent=2)
