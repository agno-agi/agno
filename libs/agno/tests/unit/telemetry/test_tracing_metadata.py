"""Tests for set_tracing_metadata: agent metadata propagation to OTel spans."""

import json
import sys
from types import ModuleType
from unittest.mock import MagicMock

from agno.agent._telemetry import set_tracing_metadata


def _make_agent(metadata=None):
    """Create a minimal Agent-like object with a metadata attribute."""
    agent = MagicMock()
    agent.metadata = metadata
    return agent


def _install_fake_otel():
    """Install a fake opentelemetry.trace module into sys.modules and return the mock span getter."""
    fake_trace = ModuleType("opentelemetry.trace")
    fake_otel = ModuleType("opentelemetry")
    fake_otel.trace = fake_trace  # type: ignore[attr-defined]

    mock_get_current_span = MagicMock()
    fake_trace.get_current_span = mock_get_current_span  # type: ignore[attr-defined]

    sys.modules["opentelemetry"] = fake_otel
    sys.modules["opentelemetry.trace"] = fake_trace

    return mock_get_current_span


def _uninstall_fake_otel():
    """Remove fake opentelemetry modules from sys.modules."""
    sys.modules.pop("opentelemetry.trace", None)
    sys.modules.pop("opentelemetry", None)


class TestSetTracingMetadata:
    """Unit tests for set_tracing_metadata."""

    def test_noop_when_metadata_is_none(self):
        """Should not touch OTel when metadata is None."""
        agent = _make_agent(metadata=None)
        # set_tracing_metadata should return early without importing opentelemetry
        set_tracing_metadata(agent)

    def test_noop_when_metadata_is_empty(self):
        """Should not touch OTel when metadata is an empty dict."""
        agent = _make_agent(metadata={})
        set_tracing_metadata(agent)

    def test_noop_when_opentelemetry_not_installed(self):
        """Should silently skip when opentelemetry is not installed."""
        agent = _make_agent(metadata={"key": "value"})
        # Ensure opentelemetry is NOT available
        _uninstall_fake_otel()
        # Should not raise
        set_tracing_metadata(agent)

    def test_sets_metadata_on_active_span(self):
        """Should set serialized metadata on the active recording span."""
        agent = _make_agent(metadata={"department": "finance", "cost_center": "dept_123"})

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True

        mock_get = _install_fake_otel()
        mock_get.return_value = mock_span
        try:
            set_tracing_metadata(agent)

            expected = json.dumps(
                {"department": "finance", "cost_center": "dept_123"},
                ensure_ascii=False,
            )
            mock_span.set_attribute.assert_called_once_with("metadata", expected)
        finally:
            _uninstall_fake_otel()

    def test_noop_when_span_not_recording(self):
        """Should not set attributes on a non-recording span."""
        agent = _make_agent(metadata={"key": "value"})

        mock_span = MagicMock()
        mock_span.is_recording.return_value = False

        mock_get = _install_fake_otel()
        mock_get.return_value = mock_span
        try:
            set_tracing_metadata(agent)
            mock_span.set_attribute.assert_not_called()
        finally:
            _uninstall_fake_otel()

    def test_noop_when_no_active_span(self):
        """Should not raise when get_current_span returns None."""
        agent = _make_agent(metadata={"key": "value"})

        mock_get = _install_fake_otel()
        mock_get.return_value = None
        try:
            set_tracing_metadata(agent)
        finally:
            _uninstall_fake_otel()

    def test_exception_in_set_attribute_is_swallowed(self):
        """Should never let tracing errors break the agent run."""
        agent = _make_agent(metadata={"key": "value"})

        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        mock_span.set_attribute.side_effect = RuntimeError("boom")

        mock_get = _install_fake_otel()
        mock_get.return_value = mock_span
        try:
            # Should not raise
            set_tracing_metadata(agent)
        finally:
            _uninstall_fake_otel()
