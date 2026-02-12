# Review Log: multimodal

> Updated: 2026-02-11

## Framework Issues

(none found — Audio, Image, File media types all work correctly with teams)

## Cookbook Quality

[QUALITY] audio_sentiment_analysis.py — Good multi-turn demo with SQLite session persistence and `add_history_to_context=True`. Second turn correctly leverages conversation history for deeper analysis without re-sending audio.

[QUALITY] audio_to_text.py — Clean minimal example. No session persistence — single-turn transcription only.

[QUALITY] generate_image_with_team.py — Good streaming events demo with `stream_events=True` and manual `RunOutputEvent` iteration. Shows how to access full team coordination metadata during streaming.

[QUALITY] image_to_structured_output.py — Excellent demo of `output_schema=MovieScript` on a Team. Streaming still works with structured output — tokens arrive one-by-one, then final Pydantic object is printed.

[QUALITY] image_to_text.py — **Missing `sample.jpg`** — cookbook references `Path(__file__).parent / "sample.jpg"` but no sample image is included. Should either bundle a sample image or use a public URL like the other cookbooks do.

[QUALITY] media_input_for_tool.py — Interesting pattern: `store_media=True` + `send_media_to_model=False` means files are stored on the run context but NOT sent to the model's vision API. Instead, the custom Toolkit's `extract_text_from_pdf` receives `files: Optional[Sequence[File]]` directly. Good demo of tool-based media processing vs model-based vision.

[QUALITY] video_caption_generation.py — Has an unresolved template variable: `"Generate captions for {video with location}"` — the `{video with location}` is a literal string, not a Python f-string. Should either be a real path or an f-string with a variable.

## Fixes Applied

(none — FAIL/SKIP items are missing dependencies, not v2.5 issues)
