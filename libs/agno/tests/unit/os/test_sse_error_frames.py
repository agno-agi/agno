"""SSE error frames must be valid JSON regardless of the exception text.

The hand-built frames interpolated str(e) straight into an f-string JSON
literal: any exception message containing a quote, backslash, or newline
emitted an invalid-JSON data payload on the wire (and a raw newline would
additionally break SSE framing). Every error frame now goes through
json.dumps via the shared sse_error_frame helper.
"""

import json

import pytest

HOSTILE = 'backend said "boom" \\ and\nnewline'


def _parse_error_frame(frame: str) -> dict:
    assert frame.startswith("event: error\ndata: "), f"not an error frame: {frame!r}"
    data_line, _, rest = frame[len("event: error\n") :].partition("\n")
    assert rest == "\n", "the data payload must stay a single SSE data line"
    return json.loads(data_line[len("data: ") :])


class TestSseErrorFrameHelper:
    def test_hostile_message_round_trips(self):
        from agno.os.utils import sse_error_frame

        payload = _parse_error_frame(sse_error_frame(HOSTILE))
        assert payload == {"event": "error", "error": HOSTILE}


class TestTailFailureFrameIsParseable:
    @pytest.mark.asyncio
    async def test_dying_tail_emits_valid_json(self, monkeypatch):
        """Drive the real queued tail streamer with a backend whose tail
        raises a hostile exception: the emitted error frame must parse."""
        from agno.os.utils import queued_run_tail_streamer

        class BoomStream:
            def tail(self, run_id, last_event_index=None):
                async def _gen():
                    raise Exception(HOSTILE)
                    yield  # pragma: no cover - makes this an async generator

                return _gen()

            async def get_run_status(self, run_id):
                return None

        monkeypatch.setattr("agno.os.event_streams.get_event_stream", lambda: BoomStream())

        frames = [chunk async for chunk in queued_run_tail_streamer("r-frame")]

        error_frames = [f for f in frames if f.startswith("event: error")]
        assert error_frames, f"a dying tail must emit an error frame, got {frames!r}"
        payload = _parse_error_frame(error_frames[0])
        assert payload["event"] == "error"
        assert 'backend said "boom"' in payload["error"]
