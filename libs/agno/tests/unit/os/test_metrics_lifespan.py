"""Tests for the background metrics calculation of the AgentOS lifespan."""

import asyncio
import threading
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agno.db.postgres import PostgresDb
from agno.os.app import metrics_lifespan
from agno.os.settings import AgnoAPISettings


class TestMetricsLifespan:
    """The background calculation keeps only the days it built, so a first build never holds every row it wrote."""

    @pytest.mark.asyncio
    async def test_the_minute_tick_keeps_only_the_days_it_calculated(self):
        calculated = threading.Event()
        db = MagicMock(spec=PostgresDb)
        db.calculate_metrics_dates = MagicMock(side_effect=lambda **kwargs: calculated.set() or [date(2026, 1, 1)])
        agent_os = SimpleNamespace(dbs={"db-1": [db]}, settings=AgnoAPISettings())

        async with metrics_lifespan(SimpleNamespace(), agent_os):
            # The first calculation runs at startup; wait for it instead of for the clock
            assert await asyncio.to_thread(calculated.wait, 5)

        db.calculate_metrics_dates.assert_called_once()
        db.calculate_metrics.assert_not_called()
