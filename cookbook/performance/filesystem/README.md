# Filesystem performance comparison

Compares the current Agno checkout with LangGraph's Deep Agents filesystem,
Mastra LocalFilesystem, Turso AgentFS, and plain local files. This directory is
self-contained and does not change framework implementation code.

Three separate experiments answer different questions:

1. **Without an agent:** direct read, write, recursive list, and substring search
   latency; resident RAM; exact storage correctness; fresh-process persistence.
2. **With a mocked agent:** native Agno, LangGraph, and Mastra tool dispatch over
   a real filesystem read. No model API calls. This measures framework overhead,
   not answer accuracy.
3. **With a real model:** one controlled OpenAI Responses agent loop shared by
   every storage backend. It measures retrieval, multi-file answers, absent
   information, saved memory, updated memory, citations, tokens, and latency.
   Native framework prompts and memory products are deliberately held out of
   this experiment so it isolates filesystem effects.

## Setup

Use an isolated environment, as the comparison needs newer LangGraph and
Deep Agents dependencies than this checkout's existing development environment.
Run from the repository root:

```bash
uv venv /private/tmp/agno-fs-bench-venv --python .venv/bin/python
uv pip install --python /private/tmp/agno-fs-bench-venv/bin/python \
  -e ./libs/agno -r cookbook/performance/filesystem/requirements.txt
npm ci --prefix cookbook/performance/filesystem
```

The reference run installed Node dependencies in
`/private/tmp/agno-fs-bench-node`; `--node-prefix` accepts either directory.
The Python dependency snapshot and Node lockfile pin the measured packages.
Install `rg` to match the recorded Deep Agents native grep configuration.

## Run

```bash
/private/tmp/agno-fs-bench-venv/bin/python cookbook/performance/filesystem/run.py \
  --node-prefix cookbook/performance/filesystem \
  --sizes 100 1000 --repeats 3 --iterations 20

/private/tmp/agno-fs-bench-venv/bin/python cookbook/performance/filesystem/report.py \
  cookbook/performance/filesystem/results
```

Every backend/size/repetition runs sequentially in a fresh process, in a seeded
random order. Each stores an identical deterministic corpus of 4 KiB UTF-8
files, verified against an oracle outside timing. Each operation has three
warm-ups. Sparse-search evidence is in the final sorted file; common search
matches every file and returns at most ten. A separate 880,000-byte file measures
large reads. New-file timings include any parent-directory work performed by the
adapter; initial directory creation is covered by warm-up.

The 4 KiB read repeatedly accesses one known file. Agno's facade keeps quota
checks enabled with a 1 GB namespace cap; the generated workspaces stay below
the ordinary 20 MB cap too. No concurrency or fsync-normalized durability claim
is made. Read `RESULTS.md` before interpreting cross-backend ratios.

JSON files preserve every timing sample, corpus hash, package version, memory
measurement and correctness result. `manifest.json` records execution order,
source commit and errors. Scratch stores stay under a fresh system temporary
directory. Results, stores, and secrets are not committed. `RESULTS.md` records
the measured summary and limitations.

The raw adapter contract uses exact UTF-8 contents, not rendered agent-tool
output. Agno facade and backend-only timings are separate. Backend-only bypasses
quotas and must not be presented as equivalent feature coverage. Native tools
have different names, truncation and output behavior, so the mocked-agent test
gives each framework one matching custom `read_file` tool. No shell tools or
model-driven host access are exposed.

## Real-model accuracy

Configure `OPENAI_API_KEY` in the environment or this directory's gitignored
`.env`. Do not put credentials in a command, result artifact, or tracked file.

```bash
/private/tmp/agno-fs-bench-venv/bin/python cookbook/performance/filesystem/agent_accuracy.py \
  --node-prefix cookbook/performance/filesystem \
  --model gpt-5.6-luna --repeats 3
```

This makes paid model calls using only synthetic data. Every question starts
with an empty transcript. Recall questions also reopen the storage adapter;
Node adapters restart their process. One client and identical schemas are reused.
The model must actually save and update files; grading checks the stored JSON,
preservation of unrelated fields, exact answers and required citations. Tool
traces and provider token counts are saved. Node tool timings include local RPC;
raw filesystem measurements above do not. Three repeats are an exploratory
sample, not enough for a robust model-quality ranking.

`agent_accuracy.py` exits clearly if no key exists, and saves provider failures
without credential values. No mocked or scripted result is labeled semantic
accuracy. Real-model tests use the same Responses agent harness across storage
providers; this is not an end-to-end ranking of native Agno/Deep Agents/Mastra
agents, nor of their separate automatic memory systems.

## Sources

- Agno implementation in `libs/agno/agno/fs/` at the recorded checkout commit.
- [Deep Agents filesystem backends](https://docs.langchain.com/oss/python/deepagents/backends).
- [Mastra LocalFilesystem](https://mastra.ai/reference/workspace/local-filesystem).
- [AgentFS SDK](https://github.com/tursodatabase/agentfs).

The installed package implementations are the runtime authority. In particular,
Mastra 1.67.0's contained local filesystem requires relative paths; documentation
examples showing a leading slash do not match that installed provider.
