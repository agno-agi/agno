# Audio Classification

Assign a label to an audio clip. Same primitive as text classification
with audio input.

## Files

- `basic.py` — single label per clip (language identification).
- `with_confidence.py` — adds confidence in the label.

## When to use

- Language routing in a multilingual voicemail system.
- Genre tagging for a music library.
- Emotion / tone gating in customer support audio.

## Models

Uses Gemini for native audio input. Replace the `Gemini(...)` line with an
audio-capable model from another provider if needed.

## Run

```bash
python cookbook/data_labeling/audio_classification/basic.py
python cookbook/data_labeling/audio_classification/with_confidence.py
```

Requires `GOOGLE_API_KEY`.
