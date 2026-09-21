# Filesystem benchmark results

Measured: 2026-09-21T18:52:32.872937+00:00

Source commit: `8fe5a2882aa353b590d9e478e841e8085a5e41d2`. Agno uses the working checkout.

Machine: macOS-26.6.2-arm64-arm-64bit; Python 3.12.8; Node v22.22.3.

Each cell below is the median of fresh-process repetition medians, in milliseconds. Each repetition has three warm-ups and 20 timed operations. OS caches are warm; caches were not flushed. No measurements are cold-disk latency. These are single-machine exploratory measurements, not universal performance rankings.

Versions: @mastra/core `1.67.0`, agentfs-sdk `0.6.4`, agno `3.0.10`, deepagents `0.7.16`, langchain `1.4.2`, langgraph `1.2.12`, psutil `7.2.2`, sqlalchemy `2.0.54`.

## 100 files × 4 KiB

| Backend | Repeats | Read 4K | Create 4K | Overwrite 4K | List | Search sparse | Search common / 10 | Read 880K |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| agentfs | 3 | 5.014 | 25.010 | 14.935 | 0.602 | 462.068 | 50.929 | 6.209 |
| agno-local | 3 | 0.131 | 5.434 | 2.628 | 2.508 | 14.864 | 3.537 | 0.211 |
| agno-local-backend | 3 | 0.122 | 0.260 | 0.283 | 2.411 | 14.572 | 3.631 | 0.185 |
| agno-sqlite | 3 | 0.056 | 0.460 | 0.335 | 0.128 | 0.315 | 0.290 | 0.104 |
| agno-sqlite-backend | 3 | 0.060 | 0.297 | 0.268 | 0.123 | 0.335 | 0.302 | 0.103 |
| deepagents-local | 3 | 0.095 | 0.100 | 0.134 | 24.207 | 9.325 | 13.700 | 0.140 |
| mastra-local | 3 | 0.131 | 0.138 | 0.152 | 1.291 | 14.264 | 2.577 | 0.268 |
| plain-local | 3 | 0.055 | 0.070 | 0.097 | 2.238 | 6.630 | 2.862 | 0.101 |

| Backend | Storage RSS MiB | RSS increase from process baseline MiB | Peak storage RSS MiB | Storage contract checks |
|---|---:|---:|---:|---:|
| agentfs | 162.4 | 120.6 | 162.4 | 36/36 |
| agno-local | 46.7 | 20.0 | 46.7 | 36/36 |
| agno-local-backend | 48.7 | 22.5 | 48.7 | 36/36 |
| agno-sqlite | 73.4 | 46.8 | 73.4 | 36/36 |
| agno-sqlite-backend | 73.2 | 46.4 | 73.2 | 36/36 |
| deepagents-local | 120.6 | 94.0 | 120.6 | 36/36 |
| mastra-local | 93.3 | 51.5 | 95.8 | 36/36 |
| plain-local | 32.2 | 5.2 | 32.2 | 36/36 |

| Agent + filesystem | Mocked read loop ms | RSS after agent MiB |
|---|---:|---:|
| agno-local | 0.342 | 59.1 |
| agno-sqlite | 0.239 | 78.7 |
| deepagents-local | 0.946 | 121.6 |
| mastra-local | 2.990 | 151.9 |

## 1,000 files × 4 KiB

| Backend | Repeats | Read 4K | Create 4K | Overwrite 4K | List | Search sparse | Search common / 10 | Read 880K |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| agentfs | 3 | 4.693 | 23.114 | 14.806 | 2.676 | 4948.110 | 52.020 | 6.018 |
| agno-local | 3 | 0.120 | 44.347 | 23.551 | 23.205 | 154.111 | 25.022 | 0.211 |
| agno-local-backend | 3 | 0.117 | 0.266 | 0.300 | 22.333 | 153.964 | 25.290 | 0.191 |
| agno-sqlite | 3 | 0.056 | 0.947 | 0.315 | 1.440 | 2.916 | 3.178 | 0.111 |
| agno-sqlite-backend | 3 | 0.057 | 0.235 | 0.242 | 1.235 | 2.900 | 3.072 | 0.103 |
| deepagents-local | 3 | 0.074 | 0.110 | 0.131 | 243.325 | 19.818 | 89.028 | 0.142 |
| mastra-local | 3 | 0.125 | 0.193 | 0.228 | 10.027 | 137.885 | 11.727 | 0.317 |
| plain-local | 3 | 0.036 | 0.074 | 0.119 | 20.810 | 62.203 | 20.565 | 0.113 |

| Backend | Storage RSS MiB | RSS increase from process baseline MiB | Peak storage RSS MiB | Storage contract checks |
|---|---:|---:|---:|---:|
| agentfs | 165.4 | 123.6 | 170.5 | 36/36 |
| agno-local | 68.9 | 42.3 | 68.9 | 36/36 |
| agno-local-backend | 61.2 | 34.7 | 61.2 | 36/36 |
| agno-sqlite | 107.0 | 80.3 | 107.0 | 36/36 |
| agno-sqlite-backend | 106.7 | 80.2 | 106.7 | 36/36 |
| deepagents-local | 136.0 | 109.3 | 136.0 | 36/36 |
| mastra-local | 131.6 | 89.7 | 142.1 | 36/36 |
| plain-local | 48.2 | 21.5 | 48.2 | 36/36 |

| Agent + filesystem | Mocked read loop ms | RSS after agent MiB |
|---|---:|---:|
| agno-local | 0.353 | 80.5 |
| agno-sqlite | 0.242 | 111.4 |
| deepagents-local | 0.994 | 136.4 |
| mastra-local | 3.036 | 181.1 |

## Interpretation boundaries

- Agno rows without `-backend` use the public FileSystem facade, including quotas and path handling. The `-backend` rows omit facade enforcement and only help explain overhead; they are not the recommended application API.
- Deep Agents uses public upload/download APIs for exact whole-file UTF-8 access, glob for recursive listing, and native grep for search. These are not its line-formatted agent tools. Its installed ripgrep subprocess cost is included.
- Mastra and AgentFS search use an explicit sorted list/read fallback because these storage providers do not supply the tested substring-search primitive. Mastra BM25/vector indexing and remote object stores are not measured.
- Plain local files have no application quota or isolation policy. Local writes are not fsync-normalized against database commits. SQLite rows use SqliteDb's WAL configuration; AgentFS retains its SDK defaults and updates access time on reads. This compares shipped application behavior, not equally durable storage engines.
- Mocked agent results are one real filesystem read dispatched by an agent, with two scripted model responses and no network. Agno uses Agent; Deep Agents storage uses LangChain create_agent on LangGraph; Mastra uses Agent.generate. All expose the same single custom read tool and reuse constructed agents. They do not measure real-model speed, token cost, answer accuracy, or native filesystem prompt quality.
- RAM is whole-process resident memory, including runtime, imported packages, corpus, retained allocator pages, and framework initialization. Python and Node RSS are not equivalent per-object allocation measurements. Agent RAM is measured after the storage workload; the peak storage column excludes later agent imports.
- Contract checks cover full corpus round trips, listing, empty/Unicode/CRLF content, overwrite, delete, missing file, four literal searches, and persistence in a new process. They do not certify concurrency, crash recovery, namespace security, or semantic retrieval quality.
- PostgreSQL, remote storage, concurrent writers, cold cache, binary data, and larger-than-1,000-file workspaces remain unmeasured.

Real-model accuracy is reported separately by `agent_accuracy.py`; no semantic accuracy number may be inferred from these contract checks.

## Search edge cases

- agno-local: 6/6 checks against its documented case-insensitive substring contract.
- agno-sqlite: 5/6 checks against its documented case-insensitive substring contract.
  - Query `kelvin`: expected `['kelvin.txt']`, got `[]`.

The Unicode probe is separate from the lowercase ASCII performance corpus. SQLite's ASCII prefilter can omit text containing the Kelvin sign `K` for the query `kelvin`, although Python lowercase matching (and Agno LocalFileSystem) finds it. This behavior is already documented in the current database backend's search implementation. No implementation change was made.

## Source-backed performance explanations

- `FileSystem.write` calls the backend's metadata lookup and, for growth, namespace usage. The local backend inherits list-based implementations of both. At larger file counts this makes public local writes much more expensive than backend-only writes. A direct local stat implementation is a concrete optimization candidate; namespace accounting needs separate correctness-preserving work.
- Agno local search lists and reads files in Python. Deep Agents uses ripgrep when available. Agno database search uses SQL as a prefilter, then loads matching rows and sorts/limits in Python. The latter still transfers all matching file contents for a broad query, which should be measured at larger scale before drawing production conclusions.
- AgentFS 0.6.4 updates an inode access timestamp in `readFile`. Its durable read path therefore has different semantics from a pure read. A list/read search compounds that work for every scanned file.

Official context: [Deep Agents backends](https://docs.langchain.com/oss/python/deepagents/backends), [Mastra LocalFilesystem](https://mastra.ai/reference/workspace/local-filesystem), [AgentFS](https://github.com/tursodatabase/agentfs). Installed package source and the recorded checkout were used for the implementation-specific explanations above.
