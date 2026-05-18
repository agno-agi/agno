# Video Classification

Assign a clip-level label to a video. Same primitive as image
classification with the temporal dimension folded in - the model watches
the clip and emits one label for the whole thing.

## Files

- `basic.py` — single label per clip.
- `with_confidence.py` — adds confidence in the label.

## When to use

- Content moderation gates on user-uploaded clips.
- Pre-tagging stock footage by scene type.
- Routing security camera clips by event category.

For typed event/scene extraction with timestamps, use
[`video_extraction/`](../video_extraction/).

## Run

```bash
python cookbook/data_labeling/video_classification/basic.py
python cookbook/data_labeling/video_classification/with_confidence.py
```

Requires `GOOGLE_API_KEY`. Uses Gemini for native video input.
