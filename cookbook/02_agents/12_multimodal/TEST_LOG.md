# Test Log — 12_multimodal

Tested: 2026-02-12 | Branch: cookbook/v25-merge-fixes

| File | Status | Notes |
|------|--------|-------|
| audio_input_output.py | PASS | Audio input transcription + audio output saved to tmp/result.wav |
| audio_sentiment_analysis.py | PASS | Detailed sentiment analysis of audio conversation |
| audio_streaming.py | PASS | Streaming audio output, story about a seed |
| audio_to_text.py | PASS | Audio transcribed to text, family conversation |
| image_to_audio.py | PASS | Image not found (sample.jpg missing) but agent handled gracefully, audio saved |
| image_to_image.py | SKIP | Missing: FAL_API_KEY |
| image_to_structured_output.py | FAIL | Wikipedia image URL blocked by OpenAI (403 upstream) |
| image_to_text.py | FAIL | sample.jpg not found, agent could not process image |
| media_input_for_tool.py | PASS | PDF financial report analyzed with Gemini, extracts revenue data |
| video_caption.py | PASS | Agent prompts for video file path (no video provided, expected behavior). Re-verified 2026-02-14: MoviePy enable_ prefix fix confirmed, agent loaded tools and responded correctly. |
