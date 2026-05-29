# Video Extraction

Video → typed Pydantic object. Pull events, scene descriptions, or
timestamped actions from a clip into a structured schema.

## Files

- `basic.py` — clip-level summary plus a flat list of scenes.
- `scene_descriptions.py` — one structured description per detected scene.
- `action_timestamps.py` — actions or events with start/end times in
  seconds.

## When to use

- Indexing a video archive for search.
- Generating chapters / timestamps for a long-form recording.
- Building a `(video, structured_labels)` training set.

For a single clip-level label, use
[`_13_video_classification/`](../_13_video_classification/).

## Run

```bash
python cookbook/data_labeling/_14_video_extraction/basic.py
python cookbook/data_labeling/_14_video_extraction/scene_descriptions.py
python cookbook/data_labeling/_14_video_extraction/action_timestamps.py
```

Requires `GOOGLE_API_KEY`.
