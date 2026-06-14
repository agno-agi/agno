import pytest

from agno.os.mcp import _arun_non_streaming


class _StreamByDefaultRunnable:
    def __init__(self):
        self.called_with_stream = []

    def arun(self, message, *, stream=None):
        self.called_with_stream.append(stream)

        if stream is False:
            return self._run(message)

        async def _stream():
            yield f"streamed {message}"

        return _stream()

    async def _run(self, message):
        return f"ran {message}"


@pytest.mark.asyncio
async def test_arun_non_streaming_forces_coroutine_result():
    runnable = _StreamByDefaultRunnable()

    result = await _arun_non_streaming(runnable, "hello")

    assert result == "ran hello"
    assert runnable.called_with_stream == [False]
