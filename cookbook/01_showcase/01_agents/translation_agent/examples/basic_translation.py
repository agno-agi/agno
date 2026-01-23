"""
Basic Translation
=================

Demonstrates basic translation with audio generation.

Prerequisites:
    export CARTESIA_API_KEY=your-cartesia-api-key
    export GOOGLE_API_KEY=your-google-api-key

Usage:
    python examples/basic_translation.py
"""

import base64
import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import translation_agent  # noqa: E402
from agno.utils.media import save_base64_data  # noqa: E402

# ============================================================================
# Basic Translation Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Translation Agent - Basic Translation")
    print("=" * 60)

    text = "Hello! How are you? Tell me about the weather in Paris."
    target_language = "French"

    print(f"Original: {text}")
    print(f"Target: {target_language}")
    print()
    print("Translating and generating audio...")
    print()

    try:
        response = translation_agent.run(
            f"Convert this phrase '{text}' to {target_language} and create a voice note"
        )

        print("RESPONSE:")
        print("-" * 40)
        print(response.content)
        print()

        if response.audio:
            output_dir = Path("tmp/translations")
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / "greeting_french.mp3"

            base64_audio = base64.b64encode(response.audio[0].content).decode("utf-8")
            save_base64_data(base64_data=base64_audio, output_path=str(output_path))

            print(f"Audio saved to: {output_path}")
        else:
            print("No audio was generated.")

    except Exception as e:
        print(f"Error: {e}")
        print()
        print("Note: This example requires Cartesia API credentials.")
        print("Set CARTESIA_API_KEY environment variable to use this agent.")
