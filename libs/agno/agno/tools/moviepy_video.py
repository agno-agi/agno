import json
import os
import tempfile
from contextlib import suppress
from typing import Callable, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, logger

try:
    from moviepy import ColorClip, CompositeVideoClip, TextClip, VideoFileClip  # type: ignore
except ImportError:
    raise ImportError("`moviepy` not installed. Please install using `pip install moviepy ffmpeg`")


def _make_temp_output_path(output_path: str) -> str:
    output_dir = os.path.dirname(os.path.abspath(output_path))
    filename = os.path.basename(output_path)
    stem, suffix = os.path.splitext(filename)
    fd, temp_path = tempfile.mkstemp(prefix=f".{stem}.", suffix=f".tmp{suffix}", dir=output_dir)
    os.close(fd)
    os.unlink(temp_path)
    return temp_path


def _remove_file_if_exists(path: Optional[str]) -> None:
    if path:
        with suppress(FileNotFoundError):
            os.remove(path)


class MoviePyVideoTools(Toolkit):
    """Tool for processing video files, extracting audio, and adding captions."""

    # Agno 2.x kwarg names accepted for backwards compatibility
    _legacy_param_aliases = {
        "enable_process_video": "extract_audio",
        "enable_generate_captions": "create_srt",
    }

    def __init__(
        self,
        extract_audio: bool = True,
        create_srt: bool = True,
        embed_captions: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize MoviePy video toolkit.

        Args:
            extract_audio: Enable the extract_audio tool.
            create_srt: Enable the create_srt tool.
            embed_captions: Enable the embed_captions tool.
            all: Enable all tools.
        """
        tools: List[Callable] = []
        if all or extract_audio:
            tools.append(self.extract_audio)
        if all or create_srt:
            tools.append(self.create_srt)
        if all or embed_captions:
            tools.append(self.embed_captions)

        super().__init__(name="video_tools", tools=tools, **kwargs)

    def split_text_into_lines(self, words: List[Dict]) -> List[Dict]:
        """Split transcribed words into lines based on duration and length constraints.

        Args:
            words: List of dicts with 'word', 'start', and 'end' keys.

        Returns:
            List of subtitle lines with word, start, end, and textcontents.
        """
        MAX_CHARS = 30
        MAX_DURATION = 2.5
        MAX_GAP = 1.5

        subtitles = []
        line = []
        line_duration = 0

        for idx, word_data in enumerate(words):
            line.append(word_data)
            line_duration += word_data["end"] - word_data["start"]

            temp = " ".join(item["word"] for item in line)

            duration_exceeded = line_duration > MAX_DURATION
            chars_exceeded = len(temp) > MAX_CHARS
            maxgap_exceeded = idx > 0 and word_data["start"] - words[idx - 1]["end"] > MAX_GAP

            if duration_exceeded or chars_exceeded or maxgap_exceeded:
                if line:
                    subtitle_line = {
                        "word": " ".join(item["word"] for item in line),
                        "start": line[0]["start"],
                        "end": line[-1]["end"],
                        "textcontents": line,
                    }
                    subtitles.append(subtitle_line)
                    line = []
                    line_duration = 0

        if line:
            subtitle_line = {
                "word": " ".join(item["word"] for item in line),
                "start": line[0]["start"],
                "end": line[-1]["end"],
                "textcontents": line,
            }
            subtitles.append(subtitle_line)

        return subtitles

    def create_caption_clips(
        self,
        text_json: Dict,
        frame_size: tuple,
        font="Arial",
        color="white",
        highlight_color="yellow",
        stroke_color="black",
        stroke_width=1.5,
    ) -> List[TextClip]:
        """Create word-level caption clips with highlighting effects.

        Args:
            text_json: Dict with text and timing information.
            frame_size: Tuple of (width, height) for the video frame.
            font: Font family for captions.
            color: Base text color.
            highlight_color: Color for highlighted words.
            stroke_color: Color for text outline.
            stroke_width: Width of text outline.

        Returns:
            List of MoviePy TextClip objects.
        """
        word_clips = []
        x_pos = 0
        y_pos = 0
        line_width = 0

        frame_width, frame_height = frame_size
        x_buffer = frame_width * 0.1
        max_line_width = frame_width - (2 * x_buffer)
        fontsize = int(frame_height * 0.30)

        full_duration = text_json["end"] - text_json["start"]

        for word_data in text_json["textcontents"]:
            duration = word_data["end"] - word_data["start"]

            # Create base word clip using official TextClip parameters
            word_clip = (
                TextClip(
                    text=word_data["word"],
                    font=font,
                    font_size=int(fontsize),
                    color=color,
                    stroke_color=stroke_color,
                    stroke_width=int(stroke_width),
                    method="label",
                )
                .with_start(text_json["start"])
                .with_duration(full_duration)
            )

            # Create space clip
            space_clip = (
                TextClip(text=" ", font=font, font_size=int(fontsize), color=color, method="label")
                .with_start(text_json["start"])
                .with_duration(full_duration)
            )

            word_width, word_height = word_clip.size
            space_width = space_clip.size[0]

            # Handle line wrapping
            if line_width + word_width + space_width <= max_line_width:
                word_clip = word_clip.with_position((x_pos + x_buffer, y_pos))
                space_clip = space_clip.with_position((x_pos + word_width + x_buffer, y_pos))
                x_pos += word_width + space_width
                line_width += word_width + space_width
            else:
                x_pos = 0
                y_pos += word_height + 10
                line_width = word_width + space_width
                word_clip = word_clip.with_position((x_buffer, y_pos))
                space_clip = space_clip.with_position((word_width + x_buffer, y_pos))

            word_clips.append(word_clip)
            word_clips.append(space_clip)

            # Create highlighted version
            highlight_clip = (
                TextClip(
                    text=word_data["word"],
                    font=font,
                    font_size=int(fontsize),
                    color=highlight_color,
                    stroke_color=stroke_color,
                    stroke_width=int(stroke_width),
                    method="label",
                )
                .with_start(word_data["start"])
                .with_duration(duration)
                .with_position(word_clip.pos)
            )

            word_clips.append(highlight_clip)

        return word_clips

    def parse_srt(self, srt_content: str) -> List[Dict]:
        """Convert SRT formatted content into word-level timing data.

        Args:
            srt_content: String containing SRT formatted subtitles.

        Returns:
            List of words with timing information.
        """
        words = []
        lines = srt_content.strip().split("\n\n")

        for block in lines:
            if not block.strip():
                continue

            parts = block.split("\n")
            if len(parts) < 3:
                continue

            # Parse timestamp line
            timestamp = parts[1]
            start_time, end_time = timestamp.split(" --> ")

            # Convert timestamp to seconds
            def time_to_seconds(time_str):
                h, m, s = time_str.replace(",", ".").split(":")
                return float(h) * 3600 + float(m) * 60 + float(s)

            start = time_to_seconds(start_time)
            end = time_to_seconds(end_time)

            # Get text content (could be multiple lines)
            text = " ".join(parts[2:])

            # Split text into words and distribute timing
            text_words = text.split()
            if text_words:
                time_per_word = (end - start) / len(text_words)

                for i, word in enumerate(text_words):
                    word_start = start + (i * time_per_word)
                    word_end = word_start + time_per_word
                    words.append({"word": word, "start": word_start, "end": word_end})

        return words

    def extract_audio(self, video_path: str, output_path: str) -> str:
        """Extract audio track from a video file.

        Args:
            video_path: Path to the video file.
            output_path: Path where the audio will be saved.

        Returns:
            JSON with output_path on success or error.
        """
        try:
            log_debug(f"Extracting audio from {video_path}")
            video = VideoFileClip(video_path)
            video.audio.write_audiofile(output_path)
            log_info(f"Audio extracted to {output_path}")
            return json.dumps({"output_path": output_path})
        except Exception as e:
            logger.exception("Failed to extract audio")
            return json.dumps({"error": f"Failed to extract audio: {str(e)}"})

    def create_srt(self, transcription: str, output_path: str) -> str:
        """Save transcription text to SRT formatted file.

        Args:
            transcription: Text transcription in SRT format.
            output_path: Path where the SRT file will be saved.

        Returns:
            JSON with output_path on success or error.
        """
        temp_output_path: Optional[str] = None
        try:
            log_debug(f"Creating SRT file at {output_path}")
            temp_output_path = _make_temp_output_path(output_path)
            with open(temp_output_path, "w", encoding="utf-8") as f:
                f.write(transcription)
            os.replace(temp_output_path, output_path)
            temp_output_path = None
            return json.dumps({"output_path": output_path})
        except Exception as e:
            _remove_file_if_exists(temp_output_path)
            logger.exception("Failed to create SRT file")
            return json.dumps({"error": f"Failed to create SRT file: {str(e)}"})

    def embed_captions(
        self,
        video_path: str,
        srt_path: str,
        output_path: Optional[str] = None,
        font_size: int = 24,
        font_color: str = "white",
        stroke_color: str = "black",
        stroke_width: int = 1,
    ) -> str:
        """Burn captions into a video with word-level highlighting.

        Args:
            video_path: Path to the input video file.
            srt_path: Path to the SRT caption file.
            output_path: Path for the output video. Defaults to {input}_captioned.mp4.
            font_size: Size of caption text.
            font_color: Color of caption text.
            stroke_color: Color of text outline.
            stroke_width: Width of text outline.

        Returns:
            JSON with output_path on success or error.
        """
        video = None
        final_video = None
        all_caption_clips = []
        temp_output_path: Optional[str] = None
        try:
            # If no output path provided, create one based on input video
            if output_path is None:
                output_path = video_path.rsplit(".", 1)[0] + "_captioned.mp4"

            # Load video
            video = VideoFileClip(video_path)

            # Read caption file and parse SRT
            with open(srt_path, "r", encoding="utf-8") as f:
                srt_content = f.read()

            # Parse SRT and get word timing
            words = self.parse_srt(srt_content)

            # Split into lines
            subtitle_lines = self.split_text_into_lines(words)

            # Create caption clips for each line
            for line in subtitle_lines:
                # Increase background height to accommodate larger text
                bg_height = int(video.h * 0.15)
                bg_clip = ColorClip(
                    size=(video.w, bg_height), color=(0, 0, 0), duration=line["end"] - line["start"]
                ).with_opacity(0.6)

                # Position background even closer to bottom (90% instead of 85%)
                bg_position = ("center", int(video.h * 0.90))
                bg_clip = bg_clip.with_start(line["start"]).with_position(bg_position)

                # Create word clips
                word_clips = self.create_caption_clips(line, (video.w, bg_height))

                # Combine background and words
                caption_composite = CompositeVideoClip([bg_clip] + word_clips, size=bg_clip.size).with_position(
                    bg_position
                )

                all_caption_clips.append(caption_composite)

            # Combine video with all captions
            final_video = CompositeVideoClip([video] + all_caption_clips, size=video.size)

            # Write output with optimized settings
            temp_output_path = _make_temp_output_path(output_path)
            final_video.write_videofile(
                temp_output_path,
                codec="libx264",
                audio_codec="aac",
                fps=video.fps,
                preset="medium",
                threads=4,
                # Disable default progress bar
            )
            os.replace(temp_output_path, output_path)
            temp_output_path = None

            return json.dumps({"output_path": output_path})

        except Exception as e:
            _remove_file_if_exists(temp_output_path)
            logger.exception("Failed to embed captions")
            return json.dumps({"error": f"Failed to embed captions: {str(e)}"})
        finally:
            for clip in all_caption_clips:
                with suppress(Exception):
                    clip.close()
            if final_video is not None:
                with suppress(Exception):
                    final_video.close()
            if video is not None:
                with suppress(Exception):
                    video.close()
