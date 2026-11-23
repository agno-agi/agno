# Audio Extraction

Audio → typed Pydantic object. The model listens to a call, meeting, or
voicemail and lifts structured fields into a domain schema.

## Files

- `basic.py` — generic call summary: caller intent, key topics, action.
- `meeting_notes.py` — meeting-shape schema: attendees, topics, action
  items.
- `call_summary.py` — customer support shape: issue, resolution, sentiment.

## When to use

- Populate a CRM from a sales call recording.
- Generate structured meeting minutes from a Zoom audio export.
- Build a training set of `(audio, structured_label)` pairs.

If you only need a transcript, use
[`_11_audio_transcription/`](../_11_audio_transcription/).

## Run

```bash
python cookbook/data_labeling/_12_audio_extraction/basic.py
python cookbook/data_labeling/_12_audio_extraction/meeting_notes.py
python cookbook/data_labeling/_12_audio_extraction/call_summary.py
```

Requires `GOOGLE_API_KEY`.
