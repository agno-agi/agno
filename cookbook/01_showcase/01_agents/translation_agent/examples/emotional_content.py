"""
Emotional Content Translation
=============================

Demonstrates emotion-aware translation with matching voice tone.

Prerequisites:
    export CARTESIA_API_KEY=your-cartesia-api-key
    export GOOGLE_API_KEY=your-google-api-key

Usage:
    python examples/emotional_content.py
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
# Emotional Content Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Translation Agent - Emotional Content")
    print("=" * 60)

    # Test different emotional tones
    examples = [
        {
            "text": "I'm so excited! This is the best news ever!",
            "language": "Spanish",
            "emotion": "excited",
        },
        {
            "text": "I'm deeply sorry for your loss. My thoughts are with you.",
            "language": "German",
            "emotion": "sad",
        },
        {
            "text": "This is unacceptable! I demand a refund immediately!",
            "language": "Italian",
            "emotion": "angry",
        },
    ]

    output_dir = Path("tmp/translations")
    output_dir.mkdir(parents=True, exist_ok=True)

    for i, example in enumerate(examples, 1):
        print()
        print(f"Example {i}: {example['emotion'].upper()}")
        print("-" * 40)
        print(f"Original: {example['text']}")
        print(f"Target: {example['language']}")
        print()

        try:
            response = translation_agent.run(
                f"Translate '{example['text']}' to {example['language']} "
                f"with appropriate emotional tone and create a voice note"
            )

            # Print abbreviated response
            content = str(response.content)
            if len(content) > 300:
                print(content[:300] + "...")
            else:
                print(content)

            if response.audio:
                filename = f"{example['emotion']}_{example['language'].lower()}.mp3"
                output_path = output_dir / filename
                base64_audio = base64.b64encode(response.audio[0].content).decode(
                    "utf-8"
                )
                save_base64_data(base64_data=base64_audio, output_path=str(output_path))
                print(f"Audio saved: {output_path}")

        except Exception as e:
            print(f"Error: {e}")

        print()
