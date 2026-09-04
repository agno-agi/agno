"""
Watch to Workflow
=================

A file lands in a folder, a pipeline runs against it. Uploads arrive as a partial
write plus a rename, so `.tmp` and `.part` are excluded -- without that the
pipeline reads half a file and then runs twice.

Prerequisites: pip install agno watchfiles
Run: .venvs/demo/bin/python cookbook/05_agent_os/26_monitor/03_watch_to_workflow.py
Try: Run this file with --demo in another terminal
"""

import sys
import time
from pathlib import Path
from typing import List

from agno.db.sqlite import SqliteDb
from agno.monitor import MonitorConfig, MonitorManager
from agno.os import AgentOS
from agno.workflow import Step, Workflow
from agno.workflow.types import StepInput, StepOutput

# The root every watch_path is contained to, and the drop folder inside it.
DROP_ROOT = Path("tmp/data_drop")
INCOMING = "incoming"

WAREHOUSE = DROP_ROOT / "warehouse.csv"

WORKFLOW_ID = "drop-pipeline"
HEADER = "order_id,sku,qty"

db = SqliteDb(id="watch-to-workflow", db_file="tmp/watch_to_workflow.db")


def changed_paths(message: str) -> List[Path]:
    """Pull the changed files out of a delivered monitor event."""
    paths: List[Path] = []
    for line in message.splitlines():
        action, _, path = line.partition(" ")
        if action in ("added", "modified", "deleted") and path.strip():
            paths.append(Path(path.strip()))
    return paths


def validate_drop(step_input: StepInput) -> StepOutput:
    """Step 1. Keep the complete CSVs, and stop if none are."""
    changed = changed_paths(str(step_input.input or ""))
    candidates = [p for p in changed if p.suffix == ".csv" and p.is_file()]
    if not candidates:
        return StepOutput(
            content="Nothing to load: the event named no readable CSV file.", stop=True
        )

    accepted: List[str] = []
    rejected: List[str] = []
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) < 2 or lines[0].strip() != HEADER:
            rejected.append(
                f"{path.name} (expected header '{HEADER}' and at least one row)"
            )
            continue
        accepted.append(str(path))

    if not accepted:
        return StepOutput(content="Rejected: " + "; ".join(rejected), stop=True)
    return StepOutput(content="\n".join(accepted))


def transform_drop(step_input: StepInput) -> StepOutput:
    """Step 2. Normalise every accepted file into one batch of rows."""
    rows: List[str] = []
    skipped = 0
    for raw in (step_input.previous_step_content or "").splitlines():
        path = Path(raw.strip())
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            fields = [field.strip() for field in line.split(",")]
            if len(fields) != 3 or not fields[2].isdigit():
                skipped += 1
                continue
            order_id, sku, qty = fields
            rows.append(f"{order_id},{sku.upper()},{int(qty)}")

    if not rows:
        return StepOutput(
            content=f"Nothing to load: {skipped} malformed row(s) and no usable ones.",
            stop=True,
        )
    print(f"Transformed {len(rows)} row(s), skipped {skipped}")
    return StepOutput(content="\n".join(rows))


def load_drop(step_input: StepInput) -> StepOutput:
    """Step 3. Append the batch to the warehouse file."""
    batch = (step_input.previous_step_content or "").splitlines()
    rows = [row for row in batch if row.strip()]
    WAREHOUSE.parent.mkdir(parents=True, exist_ok=True)
    write_header = not WAREHOUSE.exists()
    with WAREHOUSE.open("a", encoding="utf-8") as handle:
        if write_header:
            handle.write(HEADER + "\n")
        for row in rows:
            handle.write(row + "\n")
    return StepOutput(content=f"Loaded {len(rows)} row(s) into {WAREHOUSE}")


drop_pipeline = Workflow(
    id=WORKFLOW_ID,
    name="Drop Pipeline",
    description="Validate, transform and load a CSV dropped into the incoming folder.",
    db=db,
    steps=[
        Step(name="Validate", executor=validate_drop),
        Step(name="Transform", executor=transform_drop),
        Step(name="Load", executor=load_drop),
    ],
)


agent_os = AgentOS(
    name="Drop Pipeline OS",
    workflows=[drop_pipeline],
    db=db,
    monitors=MonitorConfig(
        base_dir=str(DROP_ROOT),
        poll_interval=2,  # seconds between poll cycles (default: 5)
    ),
)
app = agent_os.get_app()


def ensure_monitor() -> None:
    """Create the drop watch once, so a server restart reuses the same row."""
    # A path watch refuses to start on a path that is not there, so the drop
    # folder has to exist before the poller claims the monitor.
    (DROP_ROOT / INCOMING).mkdir(parents=True, exist_ok=True)

    manager = MonitorManager(db=db, base_dir=str(DROP_ROOT))
    existing = manager.list(status=None)
    if existing:
        print(f"Reusing monitor {existing[0].id} ({existing[0].status})")
        return

    monitor = manager.create(
        name="pipeline-on-drop",
        watch_path=INCOMING,
        description="Run the load pipeline when a file lands in the drop folder",
        # A workflow run endpoint. The event arrives as a background run exactly
        # as it would for an agent or a team.
        endpoint=f"/workflows/{WORKFLOW_ID}/runs",
        payload={"message": "A file landed in the drop folder. Load it."},
        exclude=["*.tmp", "*.part"],
        persistent=True,  # watch until stopped, with no timeout
        # Every delivered event starts a real workflow run, so a persistent
        # delivering monitor needs a ceiling.
        max_events=50,
    )
    print(
        f"Watching {DROP_ROOT / INCOMING} as monitor {monitor.id}, excluding {monitor.exclude}"
    )


def run_demo() -> None:
    """Drop a file the way a real uploader does, then show what the pipeline loaded."""
    import httpx

    with httpx.Client(base_url="http://127.0.0.1:7777", timeout=30) as client:
        try:
            client.get("/health")
        except httpx.ConnectError:
            print("No AgentOS on http://127.0.0.1:7777.")
            print("Start it first, in another terminal:")
            print("    python cookbook/05_agent_os/26_monitor/03_watch_to_workflow.py")
            return

        monitor_id = client.get("/monitors").json()["data"][0]["id"]
        seen = client.get(f"/monitors/{monitor_id}/events").json()["meta"][
            "total_count"
        ]

        # The pipeline appends, so a second --demo would show both runs' rows.
        WAREHOUSE.unlink(missing_ok=True)

        incoming = DROP_ROOT / INCOMING
        incoming.mkdir(parents=True, exist_ok=True)
        partial = incoming / "orders.csv.tmp"
        print(f"Writing {partial} (a partial upload -- excluded, so nothing fires)")
        partial.write_text("order_id,sku,qty\n1001,abc-1,2\n")
        time.sleep(5)
        after_partial = client.get(f"/monitors/{monitor_id}/events").json()["meta"][
            "total_count"
        ]
        print(f"  events so far: {after_partial - seen}")

        final = incoming / "orders.csv"
        print(f"Renaming it to {final} (this is the real drop)")
        partial.rename(final)

        print("Waiting for the pipeline...")
        for _ in range(60):
            time.sleep(2)
            events = client.get(f"/monitors/{monitor_id}/events").json()["data"]
            if len(events) > after_partial:
                print(f"Event: {events[0]['content']}")
                break
        else:
            print("No event was delivered.")
            return

        for _ in range(30):
            if WAREHOUSE.exists():
                print(f"\nWhat the pipeline loaded into {WAREHOUSE}:\n")
                print(WAREHOUSE.read_text().strip())
                return
            time.sleep(2)
        print("The warehouse file was never written.")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        run_demo()
        raise SystemExit
    ensure_monitor()
    agent_os.serve(app=app)
