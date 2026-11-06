from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from agno.scheduler import run_id


def test_history_ids_order_equal_or_backward_clock_readings(monkeypatch):
    readings = iter([1000, 1000, 999])
    monkeypatch.setattr(run_id, "_last_timestamp", 0)
    monkeypatch.setattr(run_id, "time", SimpleNamespace(time_ns=lambda: next(readings)))
    ids = [run_id.new_schedule_run_id() for _ in range(3)]
    assert ids == sorted(ids) and len(set(ids)) == 3
    assert ids[0] > "ffffffff-ffff-4fff-8fff-ffffffffffff"


def test_history_ids_are_unique_with_concurrent_creators(monkeypatch):
    monkeypatch.setattr(run_id, "time", SimpleNamespace(time_ns=lambda: 1000))
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda _: run_id.new_schedule_run_id(), range(100)))
    assert len(set(ids)) == 100
    timestamps = sorted(int(value.split("_")[1]) for value in ids)
    assert timestamps[-1] - timestamps[0] == 99
