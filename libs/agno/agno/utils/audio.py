import base64
import os
import wave

from agno.utils.log import log_info


def write_audio_to_file(audio, filename: str):
    """
    Write base64 encoded audio file to disk.

    :param audio: Base64 encoded audio file
    :param filename: The filepath or filename to save the audio to
    """
    wav_bytes = base64.b64decode(audio)

    # Create `filepath` directory if it doesn't exist.
    if os.path.dirname(filename):
        os.makedirs(os.path.dirname(filename), exist_ok=True)

    with open(filename, "wb") as f:
        f.write(wav_bytes)
    log_info(f"Audio file saved to {filename}")


def write_wav_audio_to_file(
    filename: str, pcm_data: bytes, channels: int = 1, rate: int = 24000, sample_width: int = 2
):
    """
    Create a WAV file from raw PCM audio data.

    Args:
        filename: The filepath to save the WAV file to
        pcm_data: Raw PCM audio data as bytes
        channels: Number of audio channels (1 for mono, 2 for stereo)
        rate: Sample rate in Hz (e.g., 24000, 44100, 48000)
        sample_width: Sample width in bytes (1, 2, or 4)
    """
    # Create directory if it doesn't exist
    if os.path.dirname(filename):
        os.makedirs(os.path.dirname(filename), exist_ok=True)

    with wave.open(filename, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_data)

    log_info(f"WAV file saved to {filename}")
