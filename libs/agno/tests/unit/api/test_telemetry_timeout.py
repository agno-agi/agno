"""Tests that telemetry API functions use the short-timeout TelemetryClient."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.api.api import TELEMETRY_TIMEOUT, Api


class TestTelemetryClientTimeout:
    """Verify TelemetryClient and AsyncTelemetryClient use the short timeout."""

    def test_telemetry_timeout_constant(self):
        """TELEMETRY_TIMEOUT should be a short value (5 seconds)."""
        assert TELEMETRY_TIMEOUT == 5

    def test_telemetry_client_uses_short_timeout(self):
        """TelemetryClient should be configured with TELEMETRY_TIMEOUT."""
        api = Api()
        client = api.TelemetryClient()
        assert client.timeout.connect == TELEMETRY_TIMEOUT
        assert client.timeout.read == TELEMETRY_TIMEOUT
        client.close()

    def test_async_telemetry_client_uses_short_timeout(self):
        """AsyncTelemetryClient should be configured with TELEMETRY_TIMEOUT."""
        api = Api()
        client = api.AsyncTelemetryClient()
        assert client.timeout.connect == TELEMETRY_TIMEOUT
        assert client.timeout.read == TELEMETRY_TIMEOUT

    def test_regular_client_uses_longer_timeout(self):
        """Regular Client should use the default 60s timeout, not the telemetry timeout."""
        api = Api()
        client = api.Client()
        assert client.timeout.connect == 60
        assert client.timeout.read == 60
        client.close()

    def test_regular_async_client_uses_longer_timeout(self):
        """Regular AsyncClient should use the default 60s timeout."""
        api = Api()
        client = api.AsyncClient()
        assert client.timeout.connect == 60
        assert client.timeout.read == 60


class TestTelemetryFunctionsUseTelemetryClient:
    """Verify that all telemetry API functions use TelemetryClient (not Client)."""

    def test_create_agent_run_uses_telemetry_client(self):
        """create_agent_run should use api.TelemetryClient()."""
        with patch("agno.api.agent.api") as mock_api:
            mock_client = MagicMock()
            mock_api.TelemetryClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_api.TelemetryClient.return_value.__exit__ = MagicMock(return_value=False)

            mock_run = MagicMock()
            mock_run.model_dump.return_value = {}

            from agno.api.agent import create_agent_run

            create_agent_run(mock_run)

            mock_api.TelemetryClient.assert_called_once()
            # Ensure the regular Client was NOT used
            mock_api.Client.assert_not_called()

    @pytest.mark.asyncio
    async def test_acreate_agent_run_uses_async_telemetry_client(self):
        """acreate_agent_run should use api.AsyncTelemetryClient()."""
        with patch("agno.api.agent.api") as mock_api:
            mock_client = AsyncMock()
            mock_context = AsyncMock()
            mock_context.__aenter__.return_value = mock_client
            mock_context.__aexit__.return_value = False
            mock_api.AsyncTelemetryClient.return_value = mock_context

            mock_run = MagicMock()
            mock_run.model_dump.return_value = {}

            from agno.api.agent import acreate_agent_run

            await acreate_agent_run(mock_run)

            mock_api.AsyncTelemetryClient.assert_called_once()
            mock_api.AsyncClient.assert_not_called()

    def test_create_team_run_uses_telemetry_client(self):
        """create_team_run should use api.TelemetryClient()."""
        with patch("agno.api.team.api") as mock_api:
            mock_client = MagicMock()
            mock_api.TelemetryClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_api.TelemetryClient.return_value.__exit__ = MagicMock(return_value=False)

            mock_run = MagicMock()
            mock_run.model_dump.return_value = {}

            from agno.api.team import create_team_run

            create_team_run(mock_run)

            mock_api.TelemetryClient.assert_called_once()
            mock_api.Client.assert_not_called()

    def test_create_workflow_run_uses_telemetry_client(self):
        """create_workflow_run should use api.TelemetryClient()."""
        with patch("agno.api.workflow.api") as mock_api:
            mock_client = MagicMock()
            mock_api.TelemetryClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_api.TelemetryClient.return_value.__exit__ = MagicMock(return_value=False)

            mock_run = MagicMock()
            mock_run.model_dump.return_value = {}

            from agno.api.workflow import create_workflow_run

            create_workflow_run(mock_run)

            mock_api.TelemetryClient.assert_called_once()
            mock_api.Client.assert_not_called()

    def test_log_os_telemetry_uses_telemetry_client(self):
        """log_os_telemetry should use api.TelemetryClient()."""
        with patch("agno.api.os.api") as mock_api:
            mock_client = MagicMock()
            mock_api.TelemetryClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_api.TelemetryClient.return_value.__exit__ = MagicMock(return_value=False)

            mock_launch = MagicMock()
            mock_launch.model_dump.return_value = {}

            from agno.api.os import log_os_telemetry

            log_os_telemetry(mock_launch)

            mock_api.TelemetryClient.assert_called_once()
            mock_api.Client.assert_not_called()

    def test_create_eval_run_telemetry_uses_telemetry_client(self):
        """create_eval_run_telemetry should use api.TelemetryClient()."""
        with patch("agno.api.evals.api") as mock_api:
            mock_client = MagicMock()
            mock_api.TelemetryClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_api.TelemetryClient.return_value.__exit__ = MagicMock(return_value=False)

            mock_eval = MagicMock()
            mock_eval.model_dump.return_value = {}

            from agno.api.evals import create_eval_run_telemetry

            create_eval_run_telemetry(mock_eval)

            mock_api.TelemetryClient.assert_called_once()
            mock_api.Client.assert_not_called()


class TestTelemetryErrorHandling:
    """Verify that telemetry functions swallow errors silently."""

    def test_create_agent_run_swallows_timeout_error(self):
        """create_agent_run should not raise on timeout errors."""
        import httpx

        with patch("agno.api.agent.api") as mock_api:
            mock_client = MagicMock()
            mock_client.post.side_effect = httpx.TimeoutException("Connection timed out")
            mock_api.TelemetryClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_api.TelemetryClient.return_value.__exit__ = MagicMock(return_value=False)

            mock_run = MagicMock()
            mock_run.model_dump.return_value = {}

            from agno.api.agent import create_agent_run

            # Should not raise
            create_agent_run(mock_run)

    def test_create_agent_run_swallows_connection_error(self):
        """create_agent_run should not raise on connection errors."""
        import httpx

        with patch("agno.api.agent.api") as mock_api:
            mock_client = MagicMock()
            mock_client.post.side_effect = httpx.ConnectError("Connection refused")
            mock_api.TelemetryClient.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_api.TelemetryClient.return_value.__exit__ = MagicMock(return_value=False)

            mock_run = MagicMock()
            mock_run.model_dump.return_value = {}

            from agno.api.agent import create_agent_run

            # Should not raise
            create_agent_run(mock_run)
