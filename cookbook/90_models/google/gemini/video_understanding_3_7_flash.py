"""
Gemini 3.7 Flash Video Understanding EAP Test
===============================================

Testing the Agentic Video Understanding feature with gemini-3.7-flash-video-understanding-eap.

Access granted via Google Gemini API early access program.
Model ID: models/gemini-3.7-flash-video-understanding-eap
"""

import time

import httpx
from agno.agent import Agent
from agno.media import Video
from agno.models.google import Gemini

# ---------------------------------------------------------------------------
# Test Videos
# ---------------------------------------------------------------------------
TEST_VIDEOS = {
    "short_clip": "https://agno-public.s3.amazonaws.com/demo/sample_seaview.mp4",
    "sample_5s": "https://download.samplelib.com/mp4/sample-5s.mp4",
}


# ---------------------------------------------------------------------------
# Test Functions
# ---------------------------------------------------------------------------
def test_basic_video_understanding(model_id: str, video_url: str) -> dict:
    """Test basic video understanding capabilities."""
    agent = Agent(
        model=Gemini(id=model_id),
        markdown=True,
    )

    print(f"\n{'=' * 60}")
    print(f"Model: {model_id}")
    print(f"Video: {video_url}")
    print("=" * 60)

    # Download video
    print("\nDownloading video...")
    response = httpx.get(video_url, timeout=30)
    video = Video(content=response.content, format="mp4")

    # Test 1: Basic description
    print("\n--- Test 1: Basic Description ---")
    start = time.time()
    result = agent.run(
        "Describe what happens in this video in detail.",
        videos=[video],
    )
    elapsed = time.time() - start
    print(f"Response ({elapsed:.2f}s):\n{result.content}")

    # Test 2: Scene breakdown (agentic understanding)
    print("\n--- Test 2: Scene-by-Scene Analysis ---")
    start = time.time()
    result = agent.run(
        "Break this video down into distinct scenes. For each scene, describe: "
        "1) What is happening visually "
        "2) Any text or objects visible "
        "3) The approximate timestamp",
        videos=[video],
    )
    elapsed = time.time() - start
    print(f"Response ({elapsed:.2f}s):\n{result.content}")

    # Test 3: Question answering about video
    print("\n--- Test 3: Video Q&A ---")
    start = time.time()
    result = agent.run(
        "What colors are most prominent in this video? What mood does it convey?",
        videos=[video],
    )
    elapsed = time.time() - start
    print(f"Response ({elapsed:.2f}s):\n{result.content}")

    return {
        "model": model_id,
        "video": video_url,
        "status": "success",
    }


def test_youtube_video(model_id: str) -> dict:
    """Test YouTube video understanding."""
    agent = Agent(
        model=Gemini(id=model_id),
        markdown=True,
    )

    youtube_url = "https://www.youtube.com/watch?v=XinoY2LDdA0"

    print(f"\n{'=' * 60}")
    print(f"Model: {model_id}")
    print(f"YouTube: {youtube_url}")
    print("=" * 60)

    print("\n--- YouTube Video Analysis ---")
    start = time.time()
    result = agent.run(
        "Analyze this video and provide: "
        "1) A summary of the content "
        "2) Key topics covered "
        "3) The intended audience",
        videos=[Video(url=youtube_url)],
    )
    elapsed = time.time() - start
    print(f"Response ({elapsed:.2f}s):\n{result.content}")

    return {
        "model": model_id,
        "video": youtube_url,
        "status": "success",
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Model IDs
    MODEL_3_7_FLASH = "gemini-3.7-flash"
    MODEL_3_7_FLASH_VIDEO_EAP = "gemini-3.7-flash-video-understanding-eap"
    MODEL_3_6_FLASH = "gemini-3.6-flash"

    print("\n" + "=" * 70)
    print("GEMINI VIDEO UNDERSTANDING TEST")
    print("=" * 70)

    # Test regular 3.7 Flash first (should work)
    print("\n\n>>> Testing Gemini 3.7 Flash (standard) <<<")
    test_basic_video_understanding(MODEL_3_7_FLASH, TEST_VIDEOS["short_clip"])

    # Test 3.6 Flash for comparison
    print("\n\n>>> Testing Gemini 3.6 Flash <<<")
    test_basic_video_understanding(MODEL_3_6_FLASH, TEST_VIDEOS["short_clip"])

    # Test 3.7 Flash Video Understanding EAP (may not be enabled)
    try:
        print("\n\n>>> Testing Gemini 3.7 Flash Video Understanding EAP <<<")
        test_basic_video_understanding(
            MODEL_3_7_FLASH_VIDEO_EAP, TEST_VIDEOS["short_clip"]
        )
    except Exception as e:
        print(f"\nError with {MODEL_3_7_FLASH_VIDEO_EAP}: {e}")
        print("EAP model not enabled - request access from Google.")
