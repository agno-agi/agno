"""Reproducible filesystem and mocked-agent benchmark coordinator."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
BACKENDS = [
    "plain-local",
    "agno-local",
    "agno-local-backend",
    "agno-sqlite",
    "agno-sqlite-backend",
    "deepagents-local",
    "mastra-local",
    "agentfs",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-prefix", required=True)
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 1000])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--backends", nargs="+", choices=BACKENDS, default=BACKENDS)
    parser.add_argument("--output", type=Path, default=HERE / "results")
    parser.add_argument("--no-agent", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="agno-fs-bench-"))
    env = {
        **os.environ,
        "AGNO_TELEMETRY": "false",
        "LANGCHAIN_TRACING_V2": "false",
        "LANGSMITH_TRACING": "false",
        "DO_NOT_TRACK": "1",
        "MASTRA_TELEMETRY_DISABLED": "true",
    }
    corpus_paths = {}
    for size in args.sizes:
        corpus = {}
        for i in range(size):
            header = f"record {i:06}\ncommon-marker\n"
            if i == size - 1:
                header += "needle-target\nliteral%_marker\n"
            corpus[f"docs/f{i:06}.txt"] = (
                header + ("filler data 0123456789\n" * 200)[: 4096 - len(header)]
            )
        corpus_path = args.output / f"corpus-{size}.json"
        corpus_path.write_text(json.dumps(corpus, sort_keys=True))
        corpus_paths[size] = str(corpus_path.resolve())
    jobs = [
        (b, size, rep)
        for rep in range(args.repeats)
        for size in args.sizes
        for b in args.backends
    ]
    random.Random(4829).shuffle(jobs)
    manifest = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": sys.version,
        "node": subprocess.check_output(["node", "--version"], text=True).strip(),
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "work_dir": str(work),
        "order_seed": 4829,
        "jobs": jobs,
        "results": [],
        "errors": [],
    }
    for backend, size, rep in jobs:
        name = f"{backend}-{size}-{rep}"
        output = (args.output / f"{name}.json").resolve()
        config = {
            "backend": backend,
            "root": str(work / name),
            "corpus": corpus_paths[size],
            "iterations": args.iterations,
            "output": str(output),
            "node_prefix": str(Path(args.node_prefix).resolve()),
            "agent": not args.no_agent
            and backend
            in ["agno-local", "agno-sqlite", "deepagents-local", "mastra-local"],
        }
        config_path = work / f"{name}.json"
        config_path.write_text(json.dumps(config))
        command = (
            ["node", str(HERE / "node_worker.mjs")]
            if backend in ["mastra-local", "agentfs"]
            else [sys.executable, str(HERE / "worker.py")]
        )
        completed = subprocess.run(
            [*command, str(config_path)],
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        (args.output / f"{name}.log").write_text(completed.stdout + completed.stderr)
        if completed.returncode:
            manifest["errors"].append(
                {"name": name, "returncode": completed.returncode}
            )
            print("FAILED", name, completed.stderr[-1200:], flush=True)
        else:
            config["verify_only"] = True
            config["output"] = str(work / f"{name}-reopen.json")
            config_path.write_text(json.dumps(config))
            verify = subprocess.run(
                [*command, str(config_path)],
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            result = json.loads(output.read_text())
            result["checks"]["fresh_process_reopen"] = (
                verify.returncode == 0
                and json.loads(Path(config["output"]).read_text())["reopen_pass"]
            )
            result["repetition"] = rep
            output.write_text(json.dumps(result, indent=2))
            manifest["results"].append(output.name)
            print(completed.stdout.strip(), flush=True)
        (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("Results:", args.output.resolve(), flush=True)
    if manifest["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
