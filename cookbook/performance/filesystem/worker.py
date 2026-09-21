"""One fresh Python process per backend / corpus / repetition."""

import argparse
import hashlib
import importlib.metadata
import itertools
import json
import os
from pathlib import Path
import resource
import statistics
import sys
import time

import psutil

from adapters import Adapter


def sample(operation, count):
    for i in range(3):
        operation(i)
    values = []
    for i in range(count):
        start = time.perf_counter_ns()
        operation(i)
        values.append((time.perf_counter_ns() - start) / 1e6)
    return values


def agent_loop(adapter, expected):
    """Build once. Only the model is mocked; tool dispatch and reads are real."""
    calls = []

    def read_file(path: str) -> str:
        """Read the full UTF-8 text of a file at path."""
        result = adapter.read(path)
        calls.append(result)
        return result or ""

    if adapter.name == "deepagents-local":
        from langchain.agents import create_agent
        from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
        from langchain_core.messages import AIMessage

        def responses():
            for i in itertools.count():
                yield AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "read_file",
                            "args": {"path": "docs/f000000.txt"},
                            "id": str(i),
                        }
                    ],
                )
                yield AIMessage(content="done")

        class FakeModel(GenericFakeChatModel):
            def bind_tools(self, tools, **kwargs):
                return self

        agent = create_agent(model=FakeModel(messages=responses()), tools=[read_file])

        def invoke(_):
            calls.clear()
            output = agent.invoke(
                {"messages": [{"role": "user", "content": "Read docs/f000000.txt."}]}
            )
            if output["messages"][-1].content != "done" or calls != [expected]:
                raise AssertionError("Agent failed to execute the real read")
    else:
        # Reuse the established performance suite's stateless mock model.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from _bench import MockToolModel, ensure_completed
        from agno.agent import Agent

        agent = Agent(
            model=MockToolModel(
                requested_tool="read_file", requested_args='{"path":"docs/f000000.txt"}'
            ),
            tools=[read_file],
            telemetry=False,
        )

        def invoke(_):
            calls.clear()
            ensure_completed(
                agent.run("Read docs/f000000.txt."),
                expected_content="done",
                expect_tool_success=True,
            )
            if calls != [expected]:
                raise AssertionError("Agent failed to execute the real read")

    return invoke


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    os.environ["AGNO_TELEMETRY"] = "false"
    process = psutil.Process()
    before = process.memory_info().rss
    start = time.perf_counter()
    adapter = Adapter(config["backend"], Path(config["root"]))
    init_ms = (time.perf_counter() - start) * 1000
    corpus = json.loads(Path(config["corpus"]).read_text())
    if config.get("verify_only"):
        actual = adapter.read("persist.txt")
        Path(config["output"]).write_text(
            json.dumps({"reopen_pass": actual == "durable-memory-4829"})
        )
        adapter.close()
        return
    seed_start = time.perf_counter()
    for path, content in corpus.items():
        adapter.write(path, content)
    seed_ms = (time.perf_counter() - seed_start) * 1000
    seeded_rss = process.memory_info().rss
    checks = {}
    checks["corpus_roundtrip"] = all(adapter.read(p) == c for p, c in corpus.items())
    checks["list_complete"] = adapter.list() == sorted(corpus)
    for key, content in [("empty", ""), ("unicode", "café 東京 🌍\r\nsecond\n")]:
        adapter.write("check.txt", content)
        checks[key] = adapter.read("check.txt") == content
    adapter.write("check.txt", "replacement")
    checks["overwrite"] = adapter.read("check.txt") == "replacement"
    adapter.delete("check.txt")
    checks["delete"] = adapter.read("check.txt") is None
    checks["missing"] = adapter.read("missing.txt") is None
    for query in [
        "needle-target",
        "common-marker",
        "not-present-xyz",
        "literal%_marker",
    ]:
        checks["search_" + query] = (
            adapter.search(query)
            == sorted(p for p, c in corpus.items() if query in c)[:10]
        )
    metrics = {}
    count = config["iterations"]
    first = "docs/f000000.txt"
    metrics["read_4k"] = sample(lambda _: adapter.read(first), count)
    metrics["list"] = sample(lambda _: adapter.list(), count)
    metrics["search_sparse"] = sample(lambda _: adapter.search("needle-target"), count)
    metrics["search_common_limit10"] = sample(
        lambda _: adapter.search("common-marker"), count
    )
    metrics["overwrite_same_size"] = sample(
        lambda _: adapter.write(first, corpus[first]), count
    )
    # Distinct paths including warm-ups: measure file creation, not overwrite.
    new_ids = itertools.count()
    metrics["create_4k"] = sample(
        lambda _: adapter.write(f"new/{next(new_ids):06}.txt", corpus[first]), count
    )
    large = "abcdefghij\n" * 80_000
    adapter.write("large.txt", large)
    metrics["read_880k"] = sample(lambda _: adapter.read("large.txt"), count)
    adapter.write("persist.txt", "durable-memory-4829")
    storage_rss = process.memory_info().rss
    storage_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        storage_peak *= 1024
    # Native framework tool dispatch, measured separately from raw operations.
    if config.get("agent"):
        start = time.perf_counter()
        invoke = agent_loop(adapter, corpus[first])
        agent_init_ms = (time.perf_counter() - start) * 1000
        metrics["agent_mock_read"] = sample(invoke, count)
    else:
        agent_init_ms = None
    versions = {}
    for name in [
        "agno",
        "deepagents",
        "langgraph",
        "langchain",
        "sqlalchemy",
        "psutil",
    ]:
        versions[name] = importlib.metadata.version(name)
    result = {
        "backend": config["backend"],
        "files": len(corpus),
        "iterations": count,
        "metrics_ms": metrics,
        "checks": checks,
        "init_ms": init_ms,
        "seed_ms": seed_ms,
        "rss_baseline_bytes": before,
        "rss_seeded_bytes": seeded_rss,
        "rss_storage_bytes": storage_rss,
        "peak_storage_rss_bytes": storage_peak,
        "rss_after_agent_bytes": process.memory_info().rss,
        "agent_init_ms": agent_init_ms,
        "versions": versions,
        "corpus_sha256": hashlib.sha256(
            Path(config["corpus"]).read_bytes()
        ).hexdigest(),
    }
    adapter.close()
    Path(config["output"]).write_text(json.dumps(result, indent=2))
    print(
        json.dumps(
            {
                "backend": config["backend"],
                "files": len(corpus),
                "checks_pass": all(checks.values()),
                "medians_ms": {
                    k: round(statistics.median(v), 4) for k, v in metrics.items()
                },
            }
        )
    )


if __name__ == "__main__":
    main()
