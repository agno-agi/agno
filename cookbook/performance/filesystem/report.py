"""Summarize saved raw samples; never starts benchmarks or makes model calls."""

import argparse
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--output", type=Path, default=HERE / "RESULTS.md")
    args = parser.parse_args()
    manifest = json.loads((args.results / "manifest.json").read_text())
    records = [json.loads((args.results / p).read_text()) for p in manifest["results"]]
    sample_counts = ", ".join(
        str(n) for n in sorted({r["iterations"] for r in records})
    )
    lines = [
        "# Filesystem benchmark results",
        "",
        "Measured: " + manifest["measured_at"],
        "",
        "Source commit: `" + manifest["commit"] + "`. Agno uses the working checkout.",
        "",
        "Machine: "
        + manifest["platform"]
        + "; Python "
        + manifest["python"].split()[0]
        + "; Node "
        + manifest["node"]
        + ".",
        "",
        "Each cell below is the median of fresh-process repetition medians, in milliseconds. "
        f"Each repetition has three warm-ups and {sample_counts} timed operations. "
        "OS caches are warm; caches were not flushed. No measurements are cold-disk latency. "
        "These are single-machine exploratory measurements, not universal performance rankings.",
        "",
    ]
    versions = {}
    for record in records:
        versions.update(record["versions"])
    lines += [
        "Versions: "
        + ", ".join(f"{name} `{version}`" for name, version in sorted(versions.items()))
        + ".",
        "",
    ]
    metrics = [
        "read_4k",
        "create_4k",
        "overwrite_same_size",
        "list",
        "search_sparse",
        "search_common_limit10",
        "read_880k",
    ]
    for size in sorted({r["files"] for r in records}):
        lines += [
            f"## {size:,} files × 4 KiB",
            "",
            "| Backend | Repeats | Read 4K | Create 4K | Overwrite 4K | List | Search sparse | Search common / 10 | Read 880K |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for backend in sorted({r["backend"] for r in records}):
            rows = [
                r for r in records if r["files"] == size and r["backend"] == backend
            ]
            if not rows:
                continue
            medians = [
                statistics.median(statistics.median(r["metrics_ms"][key]) for r in rows)
                for key in metrics
            ]
            lines.append(
                "| "
                + backend
                + " | "
                + str(len(rows))
                + " | "
                + " | ".join(f"{v:.3f}" for v in medians)
                + " |"
            )
        lines += [
            "",
            "| Backend | Storage RSS MiB | RSS increase from process baseline MiB | Peak storage RSS MiB | Storage contract checks |",
            "|---|---:|---:|---:|---:|",
        ]
        for backend in sorted({r["backend"] for r in records}):
            rows = [
                r for r in records if r["files"] == size and r["backend"] == backend
            ]
            if not rows:
                continue
            rss = statistics.median(r["rss_storage_bytes"] for r in rows) / 2**20
            delta = (
                statistics.median(
                    r["rss_storage_bytes"] - r["rss_baseline_bytes"] for r in rows
                )
                / 2**20
            )
            peak = statistics.median(r["peak_storage_rss_bytes"] for r in rows) / 2**20
            passed = sum(sum(bool(v) for v in r["checks"].values()) for r in rows)
            total = sum(len(r["checks"]) for r in rows)
            lines.append(
                f"| {backend} | {rss:.1f} | {delta:.1f} | {peak:.1f} | {passed}/{total} |"
            )
        lines += [
            "",
            "| Agent + filesystem | Mocked read loop ms | RSS after agent MiB |",
            "|---|---:|---:|",
        ]
        for backend in [
            "agno-local",
            "agno-sqlite",
            "deepagents-local",
            "mastra-local",
        ]:
            rows = [
                r
                for r in records
                if r["files"] == size
                and r["backend"] == backend
                and "agent_mock_read" in r["metrics_ms"]
            ]
            if rows:
                latency = statistics.median(
                    statistics.median(r["metrics_ms"]["agent_mock_read"]) for r in rows
                )
                rss = (
                    statistics.median(r["rss_after_agent_bytes"] for r in rows) / 2**20
                )
                lines.append(f"| {backend} | {latency:.3f} | {rss:.1f} |")
        lines += [""]
    lines += [
        "## Interpretation boundaries",
        "",
        "- Agno rows without `-backend` use the public FileSystem facade, including quotas and path handling. "
        "The `-backend` rows omit facade enforcement and only help explain overhead; they are not the recommended application API.",
        "- Deep Agents uses public upload/download APIs for exact whole-file UTF-8 access, glob for recursive listing, and native grep for search. "
        "These are not its line-formatted agent tools. Its installed ripgrep subprocess cost is included.",
        "- Mastra and AgentFS search use an explicit sorted list/read fallback because these storage providers do not supply the tested substring-search primitive. "
        "Mastra BM25/vector indexing and remote object stores are not measured.",
        "- Plain local files have no application quota or isolation policy. Local writes are not fsync-normalized against database commits. "
        "SQLite rows use SqliteDb's WAL configuration; AgentFS retains its SDK defaults and updates access time on reads. "
        "This compares shipped application behavior, not equally durable storage engines.",
        "- Mocked agent results are one real filesystem read dispatched by an agent, with two scripted model responses and no network. "
        "Agno uses Agent; Deep Agents storage uses LangChain create_agent on LangGraph; Mastra uses Agent.generate. "
        "All expose the same single custom read tool and reuse constructed agents. "
        "They do not measure real-model speed, token cost, answer accuracy, or native filesystem prompt quality.",
        "- RAM is whole-process resident memory, including runtime, imported packages, corpus, retained allocator pages, and framework initialization. "
        "Python and Node RSS are not equivalent per-object allocation measurements. Agent RAM is measured after the storage workload; "
        "the peak storage column excludes later agent imports.",
        "- Contract checks cover full corpus round trips, listing, empty/Unicode/CRLF content, overwrite, delete, missing file, four literal searches, "
        "and persistence in a new process. They do not certify concurrency, crash recovery, namespace security, or semantic retrieval quality.",
        "- PostgreSQL, remote storage, concurrent writers, cold cache, binary data, and larger-than-1,000-file workspaces remain unmeasured.",
        "",
    ]
    if manifest["errors"]:
        lines += ["Incomplete jobs: " + json.dumps(manifest["errors"]), ""]
    lines += [
        "Real-model accuracy is reported separately by `agent_accuracy.py`; no semantic accuracy number may be inferred from these contract checks.",
        "",
    ]
    edge_path = args.results / "search-contract.json"
    if edge_path.exists():
        edges = json.loads(edge_path.read_text())
        lines += ["## Search edge cases", ""]
        for backend in sorted({row["backend"] for row in edges}):
            subset = [row for row in edges if row["backend"] == backend]
            lines.append(
                f"- {backend}: {sum(row['pass'] for row in subset)}/{len(subset)} checks against its documented case-insensitive substring contract."
            )
            for row in subset:
                if not row["pass"]:
                    lines.append(
                        f"  - Query `{row['query']}`: expected `{row['expected']}`, got `{row['actual']}`."
                    )
        lines += [
            "",
            "The Unicode probe is separate from the lowercase ASCII performance corpus. "
            "SQLite's ASCII prefilter can omit text containing the Kelvin sign `K` for the query `kelvin`, "
            "although Python lowercase matching (and Agno LocalFileSystem) finds it. "
            "This behavior is already documented in the current database backend's search implementation. "
            "No implementation change was made.",
            "",
        ]
    lines += [
        "## Source-backed performance explanations",
        "",
        "- `FileSystem.write` calls the backend's metadata lookup and, for growth, namespace usage. "
        "The local backend inherits list-based implementations of both. At larger file counts this "
        "makes public local writes much more expensive than backend-only writes. "
        "A direct local stat implementation is a concrete optimization candidate; namespace accounting needs separate correctness-preserving work.",
        "- Agno local search lists and reads files in Python. Deep Agents uses ripgrep when available. "
        "Agno database search uses SQL as a prefilter, then loads matching rows and sorts/limits in Python. "
        "The latter still transfers all matching file contents for a broad query, which should be measured at larger scale before drawing production conclusions.",
        "- AgentFS 0.6.4 updates an inode access timestamp in `readFile`. Its durable read path "
        "therefore has different semantics from a pure read. A list/read search compounds that work for every scanned file.",
        "",
        "Official context: [Deep Agents backends](https://docs.langchain.com/oss/python/deepagents/backends), "
        "[Mastra LocalFilesystem](https://mastra.ai/reference/workspace/local-filesystem), "
        "[AgentFS](https://github.com/tursodatabase/agentfs). Installed package source and the recorded checkout were used for the implementation-specific explanations above.",
        "",
    ]
    args.output.write_text("\n".join(lines))
    print(args.output.resolve())


if __name__ == "__main__":
    main()
