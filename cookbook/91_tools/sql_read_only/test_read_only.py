"""Assert driver-enforced SQL boundaries against a temporary fictional warehouse."""

import importlib
import sys

import pytest
from sqlalchemy import text


def test_database_rejects_writes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sys.modules.pop("metrics_desk", None)
    module = importlib.import_module("metrics_desk")
    with module.warehouse.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM orders")).scalar() == 5
        for query in [
            "DELETE FROM orders",
            "DROP TABLE orders",
            "ATTACH DATABASE ':memory:' AS other",
            "CREATE TEMP TABLE sneaky (x int)",
        ]:
            with pytest.raises(Exception):
                connection.execute(text(query))
        assert connection.execute(text("SELECT count(*) FROM orders")).scalar() == 5
