"""
Noisy Job (support script)
==========================

A small data-processing job that logs its progress and hits a real error. This
is the thing being watched, not a lesson of its own.

It stands in for a real workload you would put a monitor on -- a batch job, an
ingestion pipeline, a training loop. It processes a list of orders, prints one
INFO line per order, and raises a genuine exception on a malformed record, so
the traceback a monitor catches is real rather than a fake `echo error`.

Run: .venvs/demo/bin/python cookbook/05_agent_os/26_monitor/_noisy_job.py
"""

import logging
import sys
import time

# ---------------------------------------------------------------------------
# Create Job
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)

ORDERS = [
    {"id": 1, "amount": 120.0, "qty": 2},
    {"id": 2, "amount": 80.0, "qty": 4},
    {"id": 3, "amount": 300.0, "qty": 0},  # qty 0 -> real ZeroDivisionError below
    {"id": 4, "amount": 50.0, "qty": 1},
]


def main() -> None:
    for order in ORDERS:
        time.sleep(0.5)
        # unit_price divides by qty -- order 3 has qty 0 and blows up for real
        unit_price = order["amount"] / order["qty"]
        logging.info("processed order %s: unit_price=%.2f", order["id"], unit_price)


# ---------------------------------------------------------------------------
# Run Job
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
