"""
yt-dlp Tools
============================

CLI-driven audio/video extraction via [yt-dlp](https://github.com/yt-dlp/yt-dlp).

USE CASES:
- Download video / audio from YouTube, Bilibili, Vimeo, X, etc.
- Extract metadata (title, duration, uploader, chapters) without downloading
- Build a video research agent that ingests links from chat or feeds
- Quickly answer "what is this video about" before committing a download

yt-dlp itself fetches, decodes, and writes the file. The agent calls yt-dlp
as a subprocess, so installation is one step:

Prerequisites:
- pip install yt-dlp
- ffmpeg must be installed and on PATH for format merging
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Optional

from agno.tools import Toolkit


# ---------------------------------------------------------------------------
# Create: Toolkit class registration
# ---------------------------------------------------------------------------
class YtDlpTools(Toolkit):
    def __init__(
        self,
        download_dir: str = "./tmp/yt_dlp",
        audio_only: bool = False,
        max_video_height: Optional[int] = 1080,
    ):
        super().__init__(name="yt_dlp_tools")

        self.download_dir = Path(download_dir).expanduser().resolve()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.audio_only = audio_only
        self.max_video_height = max_video_height

        self.register(self.extract_metadata)
        self.register(self.download_video)
        self.register(self.download_audio)
        self.register(self.list_supported_sites)

    def _build_format_arg(self) -> str:
        if self.audio_only:
            return "-x --audio-format mp3"
        if self.max_video_height is None:
            return ""
        return f"-S res:{self.max_video_height}"

    def extract_metadata(self, url: str) -> str:
        """Fetch video/audio metadata as JSON without downloading the media.

        Args:
            url: A URL supported by yt-dlp (YouTube, Bilibili, Vimeo, X, etc.)

        Returns:
            JSON string with title, uploader, duration, view_count, description,
            upload_date, and supported formats summary.
        """
        cmd = [
            "yt-dlp",
            "--skip-download",
            "--dump-json",
            "--no-warnings",
            url,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            return f"yt-dlp failed: {exc.stderr.strip() or 'unknown error'}"
        except subprocess.TimeoutExpired:
            return "yt-dlp metadata extraction timed out (>30s)"
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return proc.stdout[:2000]
        summary = {
            "id": data.get("id"),
            "title": data.get("title"),
            "uploader": data.get("uploader") or data.get("channel"),
            "duration_seconds": data.get("duration"),
            "view_count": data.get("view_count"),
            "upload_date": data.get("upload_date"),
            "description": (data.get("description") or "")[:1500],
            "webpage_url": data.get("webpage_url"),
            "tags": data.get("tags", [])[:20],
            "formats": len(data.get("formats", [])),
        }
        return json.dumps(summary, ensure_ascii=False, indent=2)

    def download_video(self, url: str, filename: Optional[str] = None) -> str:
        """Download a video to disk and return the resulting file path.

        Args:
            url: A URL supported by yt-dlp.
            filename: Optional output filename stem (without extension).

        Returns:
            Absolute path to the downloaded file, or an error message.
        """
        out_template = str(self.download_dir / "%(title).150B.%(ext)s")
        if filename:
            safe = shlex.quote(filename)
            out_template = str(self.download_dir / f"{safe}.%(ext)s")

        cmd = [
            "yt-dlp",
            "--no-playlist",
            "--no-warnings",
            self._build_format_arg(),
            "-o", out_template,
            url,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                cwd=str(self.download_dir),
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            return f"yt-dlp failed: {(exc.stderr or proc.stderr).strip()}"
        except subprocess.TimeoutExpired:
            return "yt-dlp download timed out (>10min)"

        target = self._resolve_dest(out_template)
        if target is None:
            return f"yt-dlp finished but file not found under {self.download_dir}"
        size_mb = target.stat().st_size / (1024 * 1024)
        return f"Downloaded to {target} ({size_mb:.1f} MB)"

    def download_audio(self, url: str) -> str:
        """Download audio only as MP3.

        Args:
            url: A URL supported by yt-dlp.

        Returns:
            Path to the MP3 file.
        """
        prev = self.audio_only
        self.audio_only = True
        try:
            return self.download_video(url)
        finally:
            self.audio_only = prev

    def list_supported_sites(self, query: str = "") -> str:
        """List yt-dlp supported sites, optionally filtered by substring.

        Args:
            query: Substring to filter site names (case-insensitive).

        Returns:
            Newline-separated list of supported sites, capped at 50.
        """
        try:
            proc = subprocess.run(
                ["yt-dlp", "--list-extractors"],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            return f"yt-dlp failed: {exc.stderr.strip()}"
        except FileNotFoundError:
            return "yt-dlp not on PATH — install with `pip install yt-dlp`"

        sites = [
            line.strip() for line in proc.stdout.splitlines() if line.strip()
        ]
        if query:
            q = query.lower()
            sites = [s for s in sites if q in s.lower()]
        return "\n".join(sites[:50])

    @staticmethod
    def _resolve_dest(template: str) -> Optional[Path]:
        parent = Path(template).parent
        if not parent.exists():
            return None
        candidates = sorted(
            parent.iterdir(),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# Run: cli smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="yt-dlp toolkit smoke test")
    parser.add_argument("--url", required=True, help="URL to extract metadata for")
    parser.add_argument(
        "--download-dir",
        default="./tmp/yt_dlp",
        help="Directory to write downloaded files",
    )
    args = parser.parse_args()

    tools = YtDlpTools(download_dir=args.download_dir)
    print(tools.extract_metadata(args.url))
