"""Check that a sharded pytest run ran every test in exactly one shard.

Plugin: `pytest -p shard_manifest` writes this shard's tests to $SHARD_MANIFEST.
Script: `python scripts/shard_manifest.py <manifest_dir> --splits <n>` checks all the shards.
"""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

MAX_LISTED = 20

_collected: List[str] = []


def pytest_collection_modifyitems(items: List[Any]) -> None:
    # Runs before pytest-split's trylast hook, so this is the full list.
    _collected[:] = [item.nodeid for item in items]


def pytest_collection_finish(session: Any) -> None:
    path = os.environ.get("SHARD_MANIFEST")
    if path:
        selected = [item.nodeid for item in session.items]
        Path(path).write_text(json.dumps({"collected": _collected, "selected": selected}))


def _listed(label: str, node_ids: List[str]) -> List[str]:
    shown = [f"  {node_id}" for node_id in sorted(node_ids)[:MAX_LISTED]]
    hidden = len(node_ids) - len(shown)
    return [f"{label}: {len(node_ids)}", *shown, *([f"  ... and {hidden} more"] if hidden else [])]


def find_problems(manifests: Dict[str, Dict[str, List[str]]], splits: int) -> List[str]:
    if len(manifests) != splits:
        return [f"Expected {splits} shard manifests, found {len(manifests)}"]

    problems: List[str] = []
    collections = {name: set(manifest["collected"]) for name, manifest in manifests.items()}
    expected = set().union(*collections.values())
    for name, collected in sorted(collections.items()):
        if collected != expected:
            problems += _listed(f"{name} did not collect", list(expected - collected))

    runs = Counter(node_id for manifest in manifests.values() for node_id in manifest["selected"])
    missing = [node_id for node_id in expected if node_id not in runs]
    duplicated = [node_id for node_id, count in runs.items() if count > 1]
    if missing:
        problems += _listed("Tests no shard ran", missing)
    if duplicated:
        problems += _listed("Tests run by more than one shard", duplicated)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest_dir", type=Path)
    parser.add_argument("--splits", type=int, required=True)
    args = parser.parse_args()

    manifests = {path.stem: json.loads(path.read_text()) for path in args.manifest_dir.glob("*.json")}
    problems = find_problems(manifests, args.splits)
    if problems:
        print("\n".join(problems))
        return 1

    total = sum(len(manifest["selected"]) for manifest in manifests.values())
    print(f"{total} tests ran exactly once across {args.splits} shards")
    return 0


if __name__ == "__main__":
    sys.exit(main())
