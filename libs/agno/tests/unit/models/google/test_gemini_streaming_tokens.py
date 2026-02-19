"""Tests that Gemini streaming metrics use assignment (not summation).

Gemini returns cumulative token counts in each streaming chunk. The base
class ``_populate_stream_data`` sums metrics with ``+=``, which would
inflate counts by N*actual when there are N chunks. The Gemini override
copies individual token fields so only the final cumulative value is kept,
while preserving the timer and time_to_first_token.
"""

from agno.models.base import MessageData
from agno.models.google.gemini import Gemini
from agno.models.metrics import MessageMetrics, Metrics
from agno.models.response import ModelResponse


def _make_model() -> Gemini:
    return Gemini(api_key="test-key")


def _make_delta(input_tokens: int, output_tokens: int, total_tokens: int) -> ModelResponse:
    """Create a ModelResponse delta with the given usage metrics."""
    delta = ModelResponse()
    delta.content = "chunk"
    delta.response_usage = Metrics(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )
    return delta


class TestGeminiStreamingTokenCounting:
    """Verify that cumulative Gemini usage is NOT summed across chunks."""

    def test_single_chunk_metrics(self):
        """A single chunk should set metrics directly."""
        model = _make_model()
        stream_data = MessageData()
        delta = _make_delta(input_tokens=10, output_tokens=5, total_tokens=15)

        results = list(model._populate_stream_data(stream_data, delta))

        assert len(results) == 1
        assert stream_data.response_metrics is not None
        assert stream_data.response_metrics.input_tokens == 10
        assert stream_data.response_metrics.output_tokens == 5
        assert stream_data.response_metrics.total_tokens == 15

    def test_multiple_chunks_uses_last_cumulative_value(self):
        """When multiple chunks arrive with cumulative counts, only the last
        value should be kept -- not a sum of all chunks."""
        model = _make_model()
        stream_data = MessageData()

        # Simulate 5 streaming chunks with cumulative token counts.
        # Each chunk reports the running total, not an incremental delta.
        cumulative_values = [
            (10, 2, 12),
            (10, 8, 18),
            (10, 15, 25),
            (10, 20, 30),
            (10, 25, 35),
        ]

        for input_tok, output_tok, total_tok in cumulative_values:
            delta = _make_delta(
                input_tokens=input_tok,
                output_tokens=output_tok,
                total_tokens=total_tok,
            )
            list(model._populate_stream_data(stream_data, delta))

        # The final metrics should equal the LAST chunk's cumulative value,
        # not the sum of all chunks.
        assert stream_data.response_metrics is not None
        assert stream_data.response_metrics.input_tokens == 10
        assert stream_data.response_metrics.output_tokens == 25
        assert stream_data.response_metrics.total_tokens == 35

    def test_summing_would_inflate_tokens(self):
        """Demonstrate that naive summation (the old bug) would give wrong results."""
        # If we summed the cumulative values from test_multiple_chunks, we'd get:
        # input:  10*5 = 50 (should be 10)
        # output: 2+8+15+20+25 = 70 (should be 25)
        # total:  12+18+25+30+35 = 120 (should be 35)
        model = _make_model()
        stream_data = MessageData()

        cumulative_values = [
            (10, 2, 12),
            (10, 8, 18),
            (10, 15, 25),
            (10, 20, 30),
            (10, 25, 35),
        ]

        for input_tok, output_tok, total_tok in cumulative_values:
            delta = _make_delta(
                input_tokens=input_tok,
                output_tokens=output_tok,
                total_tokens=total_tok,
            )
            list(model._populate_stream_data(stream_data, delta))

        # These assertions ensure the bug is fixed: values must NOT be
        # the inflated sums.
        assert stream_data.response_metrics.input_tokens != 50
        assert stream_data.response_metrics.output_tokens != 70
        assert stream_data.response_metrics.total_tokens != 120

    def test_chunks_without_usage_preserve_last_known(self):
        """Chunks that do not carry usage should not clear previously set metrics."""
        model = _make_model()
        stream_data = MessageData()

        # First chunk with usage
        delta1 = _make_delta(input_tokens=10, output_tokens=5, total_tokens=15)
        list(model._populate_stream_data(stream_data, delta1))

        # Second chunk without usage
        delta2 = ModelResponse()
        delta2.content = "more text"
        list(model._populate_stream_data(stream_data, delta2))

        # Metrics should still reflect the first chunk's cumulative value
        assert stream_data.response_metrics is not None
        assert stream_data.response_metrics.input_tokens == 10
        assert stream_data.response_metrics.output_tokens == 5
        assert stream_data.response_metrics.total_tokens == 15

    def test_content_still_concatenated(self):
        """Content strings should still be concatenated normally across chunks."""
        model = _make_model()
        stream_data = MessageData()

        chunks = ["Hello", " ", "world"]
        for text in chunks:
            delta = ModelResponse()
            delta.content = text
            list(model._populate_stream_data(stream_data, delta))

        assert stream_data.response_content == "Hello world"

    def test_cache_read_tokens_not_summed(self):
        """Cache read tokens (also cumulative in Gemini) should use assignment."""
        model = _make_model()
        stream_data = MessageData()

        for i in range(3):
            delta = ModelResponse()
            delta.content = "x"
            delta.response_usage = Metrics(
                input_tokens=10,
                output_tokens=5 * (i + 1),
                total_tokens=10 + 5 * (i + 1),
                cache_read_tokens=100,
            )
            list(model._populate_stream_data(stream_data, delta))

        # cache_read_tokens should be 100, not 300
        assert stream_data.response_metrics is not None
        assert stream_data.response_metrics.cache_read_tokens == 100

    def test_timer_preserved_across_chunks(self):
        """Timer and time_to_first_token should survive cumulative token assignment."""
        model = _make_model()
        stream_data = MessageData()

        # First chunk initializes metrics with timer
        delta1 = _make_delta(input_tokens=5, output_tokens=1, total_tokens=6)
        list(model._populate_stream_data(stream_data, delta1))

        assert stream_data.response_metrics is not None
        assert stream_data.response_metrics.timer is not None
        # TTFT should have been set by the base class on first content chunk
        assert stream_data.response_metrics.time_to_first_token is not None

        timer_ref = stream_data.response_metrics.timer

        # Second chunk updates tokens but must keep the same timer
        delta2 = _make_delta(input_tokens=5, output_tokens=3, total_tokens=8)
        list(model._populate_stream_data(stream_data, delta2))

        assert stream_data.response_metrics.timer is timer_ref
        assert stream_data.response_metrics.input_tokens == 5
        assert stream_data.response_metrics.output_tokens == 3

    def test_metrics_type_is_message_metrics(self):
        """The override should produce MessageMetrics (not bare Metrics/RunMetrics)."""
        model = _make_model()
        stream_data = MessageData()

        delta = _make_delta(input_tokens=10, output_tokens=5, total_tokens=15)
        list(model._populate_stream_data(stream_data, delta))

        assert isinstance(stream_data.response_metrics, MessageMetrics)
