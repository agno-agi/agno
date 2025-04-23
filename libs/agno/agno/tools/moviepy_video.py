from typing import Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, logger

try:
    from moviepy import ColorClip, CompositeVideoClip, TextClip, VideoFileClip  # type: ignore
except ImportError:
    raise ImportError("`moviepy` not installed. Please install using `pip install moviepy ffmpeg`")


class MoviePyVideoTools(Toolkit):
    """Tool for processing video files, extracting audio, transcribing and adding captions"""

    def __init__(
        self,
        process_video: bool = True,
        generate_captions: bool = True,
        embed_captions: bool = True,
        **kwargs,
    ):
        super().__init__(name="video_tools", **kwargs)

        if process_video:
            self.register(self.extract_audio)
        if generate_captions:
            self.register(self.create_srt)
        if embed_captions:
            self.register(self.embed_captions)

    def split_text_into_lines(self, words: List[Dict]) -> List[Dict]:
        """Split transcribed words into lines based on duration and length constraints
        Args:
            words: List of dictionaries containing word data with 'word', 'start', and 'end' keys
        Returns:
            List[Dict]: List of subtitle lines, each containing word, start time, end time, and text contents
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
        """Create word-level caption clips with highlighting effects
        Args:
            text_json: Dictionary containing text and timing information
            frame_size: Tuple of (width, height) for the video frame
            font: Font family to use for captions
            color: Base text color
            highlight_color: Color for highlighted words
            stroke_color: Color for text outline
            stroke_width: Width of text outline
        Returns:
            List[TextClip]: List of MoviePy TextClip objects for each word and highlight
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
        """Convert SRT formatted content into word-level timing data
        Args:
            srt_content: String containing SRT formatted subtitles
        Returns:
            List[Dict]: List of words with their timing information
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
        """Converts video to audio using MoviePy
        Args:
            video_path: Path to the video file
            output_path: Path where the audio will be saved
        Returns:
            str: Path to the extracted audio file
        """
        try:
            log_debug(f"Extracting audio from {video_path}")
            video = VideoFileClip(video_path)
            video.audio.write_audiofile(output_path)
            log_info(f"Audio extracted to {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Failed to extract audio: {str(e)}")
            return f"Failed to extract audio: {str(e)}"

    def create_srt(self, transcription: str, output_path: str) -> str:
        """Save transcription text to SRT formatted file
        Args:
            transcription: Text transcription in SRT format
            output_path: Path where the SRT file will be saved
        Returns:
            str: Path to the created SRT file, or error message if failed
        """
        try:
            log_debug(f"Creating SRT file at {output_path}")
            # Since we're getting SRT format from Whisper API now,
            # we can just write it directly to file
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(transcription)
            return output_path
        except Exception as e:
            logger.error(f"Failed to create SRT file: {str(e)}")
            return f"Failed to create SRT file: {str(e)}"

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
        """Create a new video with embedded scrolling captions and word-level highlighting
        Args:
            video_path: Path to the input video file
            srt_path: Path to the SRT caption file
            output_path: Path for the output video (optional)
            font_size: Size of caption text
            font_color: Color of caption text
            stroke_color: Color of text outline
            stroke_width: Width of text outline
        Returns:
            str: Path to the captioned video file, or error message if failed
        """
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

            all_caption_clips = []

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
            final_video.write_videofile(
                output_path,
                codec="libx264",
                audio_codec="aac",
                fps=video.fps,
                preset="medium",
                threads=4,
                # Disable default progress bar
            )

            # Cleanup
            video.close()
            final_video.close()
            for clip in all_caption_clips:
                clip.close()

            return output_path

        except Exception as e:
            logger.error(f"Failed to embed captions: {str(e)}")
            return f"Failed to embed captions: {str(e)}"
