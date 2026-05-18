# Audio Transcription

Speech-to-text on an audio clip. The simplest labeling primitive in the
audio family: input is raw audio, output is a typed transcript.

## Files

- `basic.py` — flat transcript string.
- `with_diarization.py` — segments labeled with a speaker identifier.
- `with_timestamps.py` — segments with start/end timing in seconds.

## When to use

- Building a training set for ASR fine-tuning.
- Pre-filling a CRM with call transcripts before human cleanup.
- Generating searchable text for an audio archive.

For typed call/meeting fields rather than a raw transcript, see
[`audio_extraction/`](../audio_extraction/).

## Run

```bash
python cookbook/data_labeling/audio_transcription/basic.py
python cookbook/data_labeling/audio_transcription/with_diarization.py
python cookbook/data_labeling/audio_transcription/with_timestamps.py
```

Requires `GOOGLE_API_KEY`.
