import base64
import os

from agno.utils.log import log_info


def write_audio_to_file(audio, filepath: str):
    """
    Write base64 encoded audio file to disk.

    :param audio: Base64 encoded audio file
    :param filepath: The filepath to save the audio to
    """
    wav_bytes = base64.b64decode(audio)

    # Create `filepath` directory if it doesn't exist.
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    with open(filepath, "wb") as f:
        f.write(wav_bytes)
    log_info(f"Audio file saved to {filepath}")
