"""
Batch Translation
=================

Demonstrates translating multiple phrases to different languages.

Prerequisites:
    export CARTESIA_API_KEY=your-cartesia-api-key
    export GOOGLE_API_KEY=your-google-api-key

Usage:
    python examples/batch_translate.py
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
_this_dir = Path(__file__).parent.parent
if str(_this_dir) not in sys.path:
    sys.path.insert(0, str(_this_dir))

from agent import translate_and_speak  # noqa: E402

# ============================================================================
# Batch Translation Example
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Translation Agent - Batch Translation")
    print("=" * 60)

    translations = [
        ("Welcome to our store!", "French"),
        ("Thank you for your purchase.", "Spanish"),
        ("Have a great day!", "German"),
    ]

    print()
    print("Processing batch translations...")
    print()

    for text, language in translations:
        print(f"Translating: '{text}' -> {language}")
        print("-" * 40)

        try:
            result = translate_and_speak(text, language)

            print(f"Response: {result['response'][:200]}...")
            if result["audio_path"]:
                print(f"Audio: {result['audio_path']}")
            else:
                print("Audio: Not generated")

        except Exception as e:
            print(f"Error: {e}")

        print()
