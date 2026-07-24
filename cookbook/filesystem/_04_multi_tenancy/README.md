# Multi-Tenancy

Per-user (and per-team) file stores from one static agent. Input is a `user_id` on the run; output is complete file isolation between users — no factories, no per-user agent objects, no way for a prompt to redirect the namespace.

Scoping is the explicit namespace name: identity enters only where you write it into that name.

## Files

- `basic.py` — the declarative common case: `namespace="assistant/{user_id}"`. One agent serves alice and bob with fully isolated files, and an anonymous run fails closed instead of collapsing into a shared store.
- `custom_factory.py` — the escape hatch for arbitrary policy: a callable tool factory builds the FileSystem per run from `run_context` (here: VIP users get their own tier of namespaces).
- `shared_namespace.py` — sharing is explicit, by name: a producer agent writes a namespace, a consumer agent attaches the same name with `tools(read_only=True)` — four read tools and the read-only instructions variant, no way to write.

## When to use

- Any user-facing agent that keeps working state: without `{user_id}` in the namespace, users share one file store.
- Role- or tenant-based scoping beyond a single placeholder: `custom_factory.py`.
- One agent producing records that another agent consults: `shared_namespace.py`.
- For the single-tenant basics first, see [`_01_getting_started/`](../_01_getting_started/); to inspect any of these namespaces from a script, see [`_05_operations/`](../_05_operations/).

## Run

```bash
python cookbook/filesystem/_04_multi_tenancy/basic.py
python cookbook/filesystem/_04_multi_tenancy/custom_factory.py
python cookbook/filesystem/_04_multi_tenancy/shared_namespace.py
```

Requires `OPENAI_API_KEY`.
