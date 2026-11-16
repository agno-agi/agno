"""The cookbook fixture must not exceed its persistent live-call budget."""

import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[5] / "cookbook/frameworks/reliability/ledger.py"
    spec = importlib.util.spec_from_file_location("readiness_ledger", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("HARNESS_LEDGER", str(tmp_path / "budget.sqlite"))
    monkeypatch.setenv("HARNESS_REPLICA", "test")
    monkeypatch.setenv("HARNESS_DEADLINE_UTC", "2099-01-01T00:00:00Z")
    return module


def test_concurrent_reservations_cannot_overrun_persistent_budget(ledger):
    with ledger.connect() as db:
        db.executemany("INSERT INTO attempts VALUES (?, 'test', 'test', 0)", [(str(i),) for i in range(199)])

    def reserve(_):
        try:
            ledger.reserve("test")
            return True
        except RuntimeError as error:
            assert "budget exhausted" in str(error)
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(reserve, range(16)))
    assert sum(accepted) == 1
    with ledger.connect() as db:
        assert db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 200
    with pytest.raises(RuntimeError, match="budget exhausted"):
        ledger.reserve("test")


def test_deadline_blocks_submission_before_reservation(ledger, monkeypatch):
    monkeypatch.setenv("HARNESS_DEADLINE_UTC", "2000-01-01T00:00:00Z")
    with pytest.raises(RuntimeError, match="deadline reached"):
        ledger.reserve("test")
    with ledger.connect() as db:
        assert db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0
