"""Run ten smoke cases against the suite_api.py AgentOS server and save its report."""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Run Suite Through the API
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:7777")
    parser.add_argument("--db-id", default="suite-db")
    parser.add_argument("--tag", default=None)
    parser.add_argument("--output", default="tmp/suite-api-smoke-result.json")
    args = parser.parse_args()

    payload = json.loads(Path(__file__).with_suffix(".json").read_text())
    if args.tag:
        payload["tag"] = args.tag
    request = Request(
        f"{args.url.rstrip('/')}/eval-suites?{urlencode({'db_id': args.db_id})}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    print("Running smoke suite; cases execute sequentially.", flush=True)
    with urlopen(request, timeout=1200) as response:
        result = json.load(response)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2))
    report = result["eval_data"]
    print(json.dumps({"id": result["id"], **report["summary"]}, indent=2))
    for case in report["cases"]:
        status = "PASS" if case["passed"] else "FAIL"
        print(f"{status}: {case['name']} ({case['duration_seconds']:.2f}s)")
        if case.get("error"):
            print(case["error"])
    print(f"Saved report: {output_path}")
    sys.exit(0 if report["summary"]["status"] == "PASS" else 1)
