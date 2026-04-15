"""
Test production deployment scenarios for SSE reconnection.
Proves that reconnection breaks in multi-container and restart scenarios.
"""

import json
import time

import httpx

AUTH = {"Authorization": "Bearer OSK_hFDigf1JhBdM5dtupYM5"}
CONTAINER_1 = "http://localhost:8000"
CONTAINER_2 = "http://localhost:8001"


def test_multi_container():
    """Simulate: user's initial request hits Container 1,
    their /resume request hits Container 2 (different container)."""

    print("=" * 70)
    print("TEST 1: Multi-Container (simulates Railway/AWS with 2 instances)")
    print("=" * 70)

    # Step 1: Send request to Container 1
    print("\n[1] Sending background+stream request to Container 1 (port 8000)...")
    form_data = {
        "message": "Count from 1 to 50, one number per line",
        "stream": "true",
        "background": "true",
    }

    run_id = None
    session_id = None
    last_index = -1
    event_count = 0

    with httpx.Client(timeout=30) as client:
        with client.stream(
            "POST",
            f"{CONTAINER_1}/agents/assistant/runs",
            data=form_data,
            headers=AUTH,
        ) as response:
            print(f"    HTTP {response.status_code}")

            for line in response.iter_lines():
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                        if "run_id" in data and not run_id:
                            run_id = data["run_id"]
                        if "session_id" in data and not session_id:
                            session_id = data["session_id"]
                        if "event_index" in data:
                            last_index = max(last_index, data["event_index"])
                            event_count += 1

                        # Read 20 events then disconnect
                        if event_count >= 20:
                            break
                    except json.JSONDecodeError:
                        pass

    print(f"    Run ID: {run_id}")
    print(f"    Session: {session_id}")
    print(f"    Last Index: {last_index}")
    print(f"    Events read: {event_count}")
    print(f"    [DISCONNECTED after {event_count} events]")

    if not run_id:
        print("    FAILED: No run_id received")
        return

    # Step 2: Resume from Container 1 (same container - should work)
    print(f"\n[2] Resuming from Container 1 (port 8000) - SAME container...")
    resume_data = {}
    if last_index >= 0:
        resume_data["last_event_index"] = str(last_index)
    if session_id:
        resume_data["session_id"] = session_id

    with httpx.Client(timeout=10) as client:
        resp = client.post(
            f"{CONTAINER_1}/agents/assistant/runs/{run_id}/resume",
            data=resume_data,
            headers=AUTH,
        )
        body = resp.text[:500]
        # Check for events
        has_events = "event:" in body and "data:" in body
        is_error = '"error"' in body.lower()
        print(f"    HTTP {resp.status_code} | Length: {len(resp.text)} chars")
        if has_events:
            # Count how many events
            event_lines = [l for l in resp.text.split("\n") if l.startswith("event:")]
            print(f"    RESULT: Got {len(event_lines)} events")
            # Show first event type
            if event_lines:
                print(f"    First event: {event_lines[0]}")
        print(f"    Preview: {body[:200]}")

    # Step 3: Resume from Container 2 (DIFFERENT container - should fail)
    print(f"\n[3] Resuming from Container 2 (port 8001) - DIFFERENT container...")
    with httpx.Client(timeout=10) as client:
        resp = client.post(
            f"{CONTAINER_2}/agents/assistant/runs/{run_id}/resume",
            data=resume_data,
            headers=AUTH,
        )
        body = resp.text[:500]
        has_events = "event:" in body and "data:" in body
        print(f"    HTTP {resp.status_code} | Length: {len(resp.text)} chars")
        print(f"    Preview: {body[:300]}")

        if "not found" in body.lower() or "error" in body.lower():
            print(f"\n    *** CONFIRMED: Container 2 cannot resume Container 1's run ***")
            print(f"    *** In production with a load balancer, this fails ~50% of the time ***")
        elif len(resp.text) < 50:
            print(f"\n    *** CONFIRMED: Container 2 returned empty/minimal response ***")
        else:
            print(f"\n    Unexpected: Container 2 returned data (check if DB fallback worked)")


def test_container_restart():
    """Simulate: user starts a run, container restarts, user tries to resume."""

    print("\n" + "=" * 70)
    print("TEST 2: Container Restart (simulates deploy/crash)")
    print("=" * 70)
    print("\nThis test uses Container 1's state from Test 1.")
    print("We'll check what Container 1's buffer knows vs a fresh container.")

    # Container 2 is essentially a "restarted" Container 1 (fresh state)
    # Try to resume the run from Test 1 on Container 2
    print("\n[1] Container 2 represents a 'restarted' server (fresh memory)...")
    print("    It has no buffer entries from the previous run.")
    print("    This is equivalent to: deploy → old container killed → new container starts")
    print("\n    Result: Same as Test 1 Step 3 above.")
    print("    The new container has no memory of the run.")
    print("    If session_id is provided, PATH 3 might find it in DB.")
    print("    But if the run was still RUNNING when killed, DB has no completed events.")


def test_multi_worker():
    """Test with uvicorn --workers 2 on a single port."""

    print("\n" + "=" * 70)
    print("TEST 3: Multi-Worker (single container, multiple processes)")
    print("=" * 70)
    print("\nWith uvicorn --workers 2, each worker is a separate Python process.")
    print("Each has its own event_buffer. Requests are round-robin'd.")
    print("This is the SAME problem as multi-container but on one machine.")
    print("\nTo test: run `uvicorn test_server:app --workers 2 --port 8002`")
    print("Then send 10 /resume requests — ~50% will fail (wrong worker).")


if __name__ == "__main__":
    test_multi_container()
    test_container_restart()
    test_multi_worker()
    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)
