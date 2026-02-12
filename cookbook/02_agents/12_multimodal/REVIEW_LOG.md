# REVIEW LOG

Generated: 2026-02-11 UTC (v2.5 three-layer review)

## Framework Issues

[FRAMEWORK] media/audio.py — Audio dataclass stores raw bytes in `content` field without size validation. Large audio files could exhaust memory when serialized to session state.

[FRAMEWORK] tools/fal.py — `run_model()` passes user-supplied `arguments` dict directly to fal_client without sanitization. Could allow unexpected keys to reach the Fal API.

[FRAMEWORK] tools/openai.py — `transcribe_audio()` opens file path without existence check; raises cryptic FileNotFoundError instead of a tool-friendly error message.

[FRAMEWORK] models/openai/responses.py — When `audio` modality is requested, `include` list self-extends on each call (mutable list appended in-place). Multiple runs accumulate duplicate include entries.

## Cookbook Quality

[QUALITY] audio_input_output.py — Good minimal example of bidirectional audio. Shows Audio media type for both input and output.

[QUALITY] audio_streaming.py — Demonstrates PCM16 streaming with OpenAIResponses. Good advanced pattern for real-time audio apps.

[QUALITY] audio_to_text.py — Clean Gemini transcription example. Good alternative to OpenAI Whisper.

[QUALITY] audio_sentiment_analysis.py — Shows structured output (SentimentAnalysis pydantic model) with audio input. Good combination of two features.

[QUALITY] image_to_structured_output.py — Excellent example of output_schema with vision. Clear Pydantic model definition.

[QUALITY] image_to_text.py — Simplest multimodal example. Good starting point for users.

[QUALITY] media_input_for_tool.py — Demonstrates passing media to tools with Gemini. Unique pattern not shown elsewhere.

[QUALITY] video_caption.py — Good multi-step pipeline example (extract audio, transcribe, generate SRT, embed). Placeholder video path should be documented more clearly.

## Fixes Applied

None — all cookbooks are v2.5 compatible as-is.
