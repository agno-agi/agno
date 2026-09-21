"""Real-model filesystem task accuracy under one identical agent loop.

Native framework overhead is measured separately by run.py. This experiment
holds the OpenAI Responses loop, tool schemas, prompts and model constant to
isolate the storage backend. Only synthetic benchmark data is sent to the model.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path, PurePosixPath
import random
import subprocess
import tempfile
import time

from dotenv import load_dotenv
from openai import OpenAI

from adapters import Adapter

HERE = Path(__file__).resolve().parent
BACKENDS = [
    "plain-local",
    "agno-local",
    "agno-sqlite",
    "deepagents-local",
    "mastra-local",
    "agentfs",
]
SYSTEM = """Use the filesystem to complete the task. Search before reading when the path is unknown.
Never invent unavailable information. Files are durable, but conversation history is not.
Return only a JSON object with answer (string) and sources (array of file paths).
For missing information answer UNKNOWN. For a requested write answer SAVED after writing.
For profile updates preserve every unrelated field. Do not write files on read-only questions."""
TOOLS = [
    {
        "type": "function",
        "name": "read_file",
        "description": "Read all UTF-8 text at a relative file path.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "write_file",
        "description": "Create or completely replace a UTF-8 file. Parent directories are created.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "search_content",
        "description": "Find up to 10 file paths containing the literal query. Use lowercase ASCII query text.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "list_files",
        "description": "List every file path in the workspace.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


class NodeAdapter:
    def __init__(self, name, root, node_prefix):
        config = root.parent / (root.name + "-rpc.json")
        config.write_text(
            json.dumps(
                {
                    "backend": name,
                    "root": str(root),
                    "node_prefix": node_prefix,
                    "rpc": True,
                }
            )
        )
        self.process = subprocess.Popen(
            ["node", str(HERE / "node_worker.mjs"), str(config)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )

    def call(self, op, *args):
        self.process.stdin.write(json.dumps({"op": op, "args": args}) + "\n")
        self.process.stdin.flush()
        result = json.loads(self.process.stdout.readline())
        if "error" in result:
            raise RuntimeError(result["error"])
        return result["result"]

    def read(self, path):
        return self.call("read", path)

    def write(self, path, content):
        return self.call("write", path, content)

    def list(self):
        return self.call("list")

    def search(self, query):
        return self.call("search", query)

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=30)


def run_task(client, model, adapter, prompt):
    # New input list per task, including recall tasks: no transcript leakage.
    messages = [{"role": "user", "content": prompt}]
    usage = {"input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0}
    trace = []
    start = time.perf_counter()
    for _ in range(10):
        response = client.responses.create(
            model=model,
            instructions=SYSTEM,
            input=messages,
            tools=TOOLS,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "filesystem_answer",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "answer": {"type": "string"},
                            "sources": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["answer", "sources"],
                        "additionalProperties": False,
                    },
                }
            },
            max_output_tokens=1200,
            store=False,
        )
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens
        usage["cached_input_tokens"] += (
            response.usage.input_tokens_details.cached_tokens
        )
        messages.extend(response.output)
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            try:
                answer = json.loads(response.output_text)
            except json.JSONDecodeError:
                answer = {
                    "answer": response.output_text,
                    "sources": [],
                    "invalid_json": True,
                }
            return {
                "answer": answer,
                "latency_ms": (time.perf_counter() - start) * 1000,
                "usage": usage,
                "model": response.model,
                "tool_calls": len(trace),
                "trace": trace,
            }
        for call in calls:
            args = json.loads(call.arguments)
            tool_start = time.perf_counter()
            try:
                if "path" in args:
                    candidate = PurePosixPath(args["path"])
                    if (
                        candidate.is_absolute()
                        or ".." in candidate.parts
                        or not candidate.parts
                    ):
                        raise ValueError(
                            "File paths must remain relative to the benchmark workspace"
                        )
                if call.name == "read_file":
                    result = adapter.read(args["path"])
                elif call.name == "write_file":
                    adapter.write(args["path"], args["content"])
                    result = "SAVED"
                elif call.name == "search_content":
                    result = adapter.search(args["query"])
                elif call.name == "list_files":
                    result = adapter.list()
                else:
                    raise ValueError("Unknown tool")
                output = json.dumps(result, ensure_ascii=False)
            except Exception as error:
                output = json.dumps({"error": type(error).__name__})
            trace.append(
                {
                    "name": call.name,
                    "args": args,
                    "output": output,
                    "latency_ms": (time.perf_counter() - tool_start) * 1000,
                }
            )
            messages.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": output,
                }
            )
    raise RuntimeError("Agent exceeded ten model turns")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--node-prefix", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--output", type=Path, default=HERE / "results" / "agent-accuracy.json"
    )
    args = parser.parse_args()
    load_dotenv(HERE / ".env", override=False)
    load_dotenv(override=False)
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not configured. No agent calls were made.")
    client = OpenAI(max_retries=0, timeout=60)
    root = Path(tempfile.mkdtemp(prefix="agno-fs-agent-"))
    output = {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "mode": "controlled-common-Responses-agent",
        "results": [],
        "errors": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    jobs = [(b, rep) for rep in range(args.repeats) for b in BACKENDS]
    random.Random(713).shuffle(jobs)
    for backend, rep in jobs:
        location = root / f"{backend}-{rep}"

        def open_adapter():
            return (
                NodeAdapter(backend, location, str(Path(args.node_prefix).resolve()))
                if backend in ["mastra-local", "agentfs"]
                else Adapter(backend, location)
            )

        adapter = open_adapter()
        serial = f"q7v{rep}k4829"
        profile = {
            "language": "French",
            "timezone": "Asia/Kolkata",
            "reference": serial,
        }
        files = {
            f"docs/noise{i:03}.txt": f"Historical release record {i}. Nothing is approved here."
            for i in range(40)
        }
        files.update(
            {
                "docs/current.txt": f"project orchid current release token: {serial}\nowner: Mira\n",
                "docs/long.txt": "project iris\n"
                + "Background material; not a release decision.\n" * 180
                + f"approved code: iris-{serial}\n",
                "docs/west.txt": "west shipment crates: 18\n",
                "docs/east.txt": "east shipment crates: 11\n",
            }
        )
        for p, content in files.items():
            adapter.write(p, content)
        tasks = [
            (
                "lookup",
                "Find the current release token for project orchid. Return only the token as answer.",
                serial,
                ["docs/current.txt"],
            ),
            (
                "distant_evidence",
                "Find the approved code for project iris. Return only the code as answer.",
                "iris-" + serial,
                ["docs/long.txt"],
            ),
            (
                "multi_file",
                "What is the total number of shipment crates in east and west? Return only the integer as answer.",
                "29",
                ["docs/east.txt", "docs/west.txt"],
            ),
            (
                "absent",
                "What is project zephyr's approved release token?",
                "UNKNOWN",
                [],
            ),
            (
                "save_memory",
                "Save this exact JSON in memory/profile.json: " + json.dumps(profile),
                "SAVED",
                [],
            ),
            (
                "recall_fresh_session",
                "Read my saved profile. Return my language, timezone and reference joined by |.",
                "French|Asia/Kolkata|" + serial,
                ["memory/profile.json"],
            ),
            (
                "update_memory",
                "Update memory/profile.json: my language is now Japanese. Preserve my timezone and reference.",
                "SAVED",
                [],
            ),
            (
                "recall_updated",
                "Read my saved profile. Return my language, timezone and reference joined by |.",
                "Japanese|Asia/Kolkata|" + serial,
                ["memory/profile.json"],
            ),
        ]
        try:
            for name, prompt, expected, sources in tasks:
                if name.startswith("recall"):
                    adapter.close()
                    adapter = open_adapter()
                result = run_task(client, args.model, adapter, prompt)
                answer = result["answer"]
                result.update(
                    {
                        "backend": backend,
                        "repetition": rep,
                        "task": name,
                        "answer_pass": answer.get("answer") == expected,
                        "citation_pass": set(sources) == set(answer.get("sources", []))
                        if name not in ["save_memory", "update_memory"]
                        else all(
                            adapter.read(p) is not None
                            for p in answer.get("sources", [])
                        ),
                    }
                )
                if name in ["save_memory", "update_memory"]:
                    try:
                        actual = json.loads(
                            adapter.read("memory/profile.json") or "null"
                        )
                    except json.JSONDecodeError:
                        actual = None
                    expected_profile = (
                        {**profile, "language": "Japanese"}
                        if name == "update_memory"
                        else profile
                    )
                    result["state_pass"] = actual == expected_profile and all(
                        adapter.read(p) == c for p, c in files.items()
                    )
                else:
                    result["state_pass"] = not any(
                        call["name"] == "write_file" for call in result["trace"]
                    ) and all(adapter.read(p) == c for p, c in files.items())
                result["pass"] = (
                    result["answer_pass"]
                    and result["citation_pass"]
                    and result["state_pass"]
                )
                output["results"].append(result)
                args.output.write_text(json.dumps(output, indent=2))
                print(
                    backend,
                    rep,
                    name,
                    result["pass"],
                    round(result["latency_ms"]),
                    flush=True,
                )
        except Exception as error:
            output["errors"].append(
                {
                    "backend": backend,
                    "repetition": rep,
                    "type": type(error).__name__,
                    "status_code": getattr(error, "status_code", None),
                }
            )
            args.output.write_text(json.dumps(output, indent=2))
            raise
        finally:
            adapter.close()


if __name__ == "__main__":
    main()
