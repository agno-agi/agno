"""Unit tests for OpenAITools (agno.tools.openai)."""

import inspect

from agno.tools.openai import OpenAITools


# ---------------------------------------------------------------------------
# Regression: transcribe_audio must close the audio file handle
# ---------------------------------------------------------------------------


def test_transcribe_audio_uses_context_manager_to_close_audio_file():
    """`OpenAITools.transcribe_audio` must open the audio file in a `with` block.

    Previously the method used a bare `open(audio_path, "rb")` whose result
    was bound to a local variable but never explicitly closed. On every
    successful AND failing call, a file descriptor leaked. For an agent
    transcribing audio in a loop, this exhausts the process's `RLIMIT_NOFILE`.

    The fix wraps the `open(...)` call in a `with` block so the file is
    closed deterministically at the end of the API call, whether the call
    succeeds or raises.
    """
    source = inspect.getsource(OpenAITools.transcribe_audio)

    # The fix introduces a `with open(...)` block, replacing the prior
    # `audio_file = open(...)` assignment-only pattern.
    assert "with open(" in source, (
        "transcribe_audio must open the audio file via a `with open(...)` "
        "context manager so the file descriptor is closed deterministically. "
        "Without it, every call leaks a file handle."
    )

    # The buggy pattern was `audio_file = open(audio_path, "rb")` at module
    # statement level inside try-body. Asserting it's gone catches a revert.
    assert "audio_file = open(" not in source, (
        "transcribe_audio must NOT bind the result of open() to a name "
        "without a context manager — that pattern leaks file descriptors."
    )
