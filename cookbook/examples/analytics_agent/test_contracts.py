"""Verify the seeded metric and database-enforced write rejection."""

import importlib
import runpy
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError


def test_active_mrr_and_read_only_database(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(Path(__file__).with_name("seed_data.py")), run_name="__main__")
    module = importlib.import_module("analytics_agent")
    assert module.sql.run_sql(
        "SELECT SUM(mrr_usd) AS mrr FROM subscriptions WHERE status = 'active'"
    ) == [{"mrr": 2000}]
    with pytest.raises(OperationalError, match="readonly"):
        module.sql.run_sql("UPDATE subscriptions SET mrr_usd = 0")
    with sqlite3.connect("analytics.db") as db:
        assert (
            db.execute("SELECT SUM(mrr_usd) FROM subscriptions").fetchone()[0] == 2500
        )
