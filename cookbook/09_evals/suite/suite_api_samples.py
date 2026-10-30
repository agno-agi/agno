"""List or execute twelve sample suites against the local suite_api.py server."""

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# ---------------------------------------------------------------------------
# Load Sample Definitions
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    samples = json.loads(Path(__file__).with_suffix(".json").read_text())["suites"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:7777")
    parser.add_argument("--db-id", default="suite-db")
    parser.add_argument(
        "--suite",
        type=int,
        choices=range(1, len(samples) + 1),
        help="Run only this suite number",
    )
    parser.add_argument(
        "--list", action="store_true", help="Show sample names without making requests"
    )
    parser.add_argument("--output-dir", default="tmp/suite-api-samples")
    args = parser.parse_args()
    selected = [
        (index, sample)
        for index, sample in enumerate(samples, 1)
        if args.suite in (None, index)
    ]

    if args.list:
        for _, sample in selected:
            print(f"{sample['payload']['name']} | expected {sample['expected_status']}")
        sys.exit(0)

    # -----------------------------------------------------------------------
    # Execute Suites and Save Reports
    # -----------------------------------------------------------------------
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    unexpected = 0
    for index, sample in selected:
        payload = sample["payload"]
        print(
            f"Running {payload['name']} (expected {sample['expected_status']})",
            flush=True,
        )
        request = Request(
            f"{args.url.rstrip('/')}/eval-suites?{urlencode({'db_id': args.db_id})}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=300) as response:
                result = json.load(response)
            (output_dir / f"suite-{index:02d}.json").write_text(
                json.dumps(result, indent=2)
            )
            summary = result["eval_data"]["summary"]
            matches = summary["status"] == sample["expected_status"]
            unexpected += int(not matches)
            print(
                f"{summary['status']}: {summary['passed']}/{summary['total']} passed; "
                f"run {result['id']}; expected outcome matched: {matches}",
                flush=True,
            )
        except Exception as error:
            unexpected += 1
            print(
                f"Could not finish suite {index}: {error}", file=sys.stderr, flush=True
            )

    print(f"Reports: {output_dir}; unexpected outcomes or request errors: {unexpected}")
    sys.exit(1 if unexpected else 0)
