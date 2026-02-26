# Assets

Sample media files for the multimodal steps in this guide.

## Current Status

Steps 8-14 currently download sample files from URLs at runtime. If you want to run them offline, place your own files here:

| Step | Expected File | Format | Notes |
|:-----|:-------------|:-------|:------|
| 8 | `sample_image.jpg` | JPEG/PNG | Any photo for image analysis |
| 10 | `sample_audio.mp3` | MP3/WAV | Short audio clip (< 1 min) |
| 12 | `sample_video.mp4` | MP4 | Short video clip (< 30 sec) |
| 13 | `sample.pdf` | PDF | Any document for PDF analysis |
| 14 | `sample.csv` | CSV | Any dataset with headers |

## Using Local Files

To use local files instead of URLs, update the step files:

```python
# Instead of downloading from URL:
# response = httpx.get("https://...")
# audio=[Audio(content=response.content, format="mp3")]

# Use a local file:
from pathlib import Path
audio_bytes = Path("cookbook/gemini_3/assets/sample_audio.mp3").read_bytes()
audio=[Audio(content=audio_bytes, format="mp3")]
```

## Licensing

If you add files here, ensure they are:
- Permissively licensed (CC0, CC-BY, or your own content)
- Small (< 10 MB each) to keep the repo cloneable
- Not containing PII or sensitive content
