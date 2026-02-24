"""
Code Mode — Media Generation Pipeline (Image + Audio)
======================================================
Combines DALL-E (image generation) + ElevenLabs (audio/TTS) in a single
code_mode agent. The model writes a program that:
1. Generates an image from a description
2. Generates speech narration about the image
3. Returns both media through the sideband pipeline

This validates that ToolResult with mixed media types (images + audio)
flows correctly through the code_mode media collector without serializing
binary data into the context window.

Before the fix: str(ToolResult) would dump ~40KB+ of audio bytes + image
URLs into the model context. After: media flows through RunOutput sideband.

Requires: OPENAI_API_KEY, ELEVEN_LABS_API_KEY
Run: PYTHONPATH=libs/agno .venvs/demo/bin/python cookbook/05_agent_os/code_mode/cm_media_pipeline.py
"""

import time

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.dalle import DalleTools
from agno.tools.eleven_labs import ElevenLabsTools

agent = Agent(
    model=Claude(id="claude-sonnet-4-20250514"),
    tools=[
        DalleTools(),
        ElevenLabsTools(
            voice_id="21m00Tcm4TlvDq8ikWAM",
            target_directory="tmp/media_pipeline",
        ),
    ],
    code_mode=True,
    markdown=True,
)

TASK = (
    "Create a multimedia presentation about a 'futuristic city at sunset':\n"
    "1. Generate an image of a futuristic city at sunset with flying cars\n"
    "2. Generate speech narration: 'Welcome to Neo Tokyo, year 2085. "
    "The sun sets over a skyline of crystalline towers as autonomous vehicles "
    "glide silently through the amber sky.'\n"
    "3. Store a description of what you created in `result`."
)

if __name__ == "__main__":
    t0 = time.time()
    response = agent.run(TASK)
    elapsed = time.time() - t0

    print("\n" + "=" * 60)
    print("MEDIA PIPELINE RESULTS")
    print("=" * 60)

    content = response.content or ""
    print(f"\nContent: {len(content)} chars")
    print(f"Preview: {content[:300]}")

    image_count = len(response.images) if response.images else 0
    audio_count = len(response.audio) if response.audio else 0
    print(f"\nImages: {image_count}")
    if response.images:
        for i, img in enumerate(response.images):
            has_url = img.url is not None
            has_bytes = img.content is not None
            print(f"  Image[{i}]: url={has_url}, bytes={has_bytes}")

    print(f"Audio: {audio_count}")
    if response.audio:
        for i, aud in enumerate(response.audio):
            size = len(aud.content or b"")
            print(f"  Audio[{i}]: {size:,} bytes ({size / 1024:.1f} KB)")

    content_has_bytes = "content=b'" in content or "\\x" in content
    print(f"\nByte leak in content: {content_has_bytes}")

    m = response.metrics
    if m:
        print(
            f"Tokens: {m.total_tokens:,} (input: {m.input_tokens:,}, output: {m.output_tokens:,})"
        )

    print(f"Duration: {elapsed:.1f}s")

    print("\n" + "-" * 60)
    checks = {
        "Has content": len(content) > 50,
        "Image generated": image_count >= 1,
        "Audio generated": audio_count >= 1,
        "No byte leak": not content_has_bytes,
    }
    all_pass = True
    for check, passed in checks.items():
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {check}")

    print(f"\nOVERALL: {'PASS' if all_pass else 'FAIL'}")
