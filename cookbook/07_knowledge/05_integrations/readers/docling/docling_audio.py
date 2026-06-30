"""
Docling Reader: Audio Files
============================
Examples of using Docling to process audio files with speech-to-text transcription.

Supported formats:
- WAV: Waveform Audio File Format
- MP3: MPEG Audio Layer III
- MP4: MPEG-4 Part 14 (audio)

Output formats:
- markdown: Transcription as markdown text (default)
- text: Plain text transcription
- html: HTML formatted transcription
- vtt: WebVTT subtitle format with timestamps

Docling uses OpenAI Whisper for high-quality speech recognition.

Dependencies:
- Python packages: `uv pip install docling openai-whisper`
- System requirement: ffmpeg (https://www.ffmpeg.org/download.html)
"""

import asyncio

from agno.knowledge.reader.docling_reader import DoclingReader
from utils import get_agent, get_knowledge

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

knowledge = get_knowledge(table_name="docling_audio")
agent = get_agent(knowledge)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # --- WAV audio - Agno description with HTML output ---
        print("\n" + "=" * 60)
        print("WAV audio - Agno Description (HTML output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Agno_Audio_WAV",
            path="cookbook/07_knowledge/testing_resources/agno_description.wav",
            reader=DoclingReader(output_format="html"),
        )
        agent.print_response(
            "What does the audio describe about Agno?",
            stream=True,
        )

        # --- MP3 audio - Agno description ---
        print("\n" + "=" * 60)
        print("MP3 audio - Agno Description (markdown output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Agno_Audio_MP3",
            path="cookbook/07_knowledge/testing_resources/agno_description.mp3",
            reader=DoclingReader(),
        )
        agent.print_response(
            "Summarize what Agno framework is used for",
            stream=True,
        )

        # --- MP4 audio - Agno description with VTT output ---
        print("\n" + "=" * 60)
        print("MP4 audio - Agno Description (VTT output)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Agno_Audio_MP4",
            path="cookbook/07_knowledge/testing_resources/agno_description.mp4",
            reader=DoclingReader(output_format="vtt"),
        )
        agent.print_response(
            "What are the key features of Agno mentioned in the audio?",
            stream=True,
        )

    asyncio.run(main())
