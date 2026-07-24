# Multi-Tenancy

Per-user (and per-team) file stores from one static agent. Put a `user_id` on the run and users get completely isolated files, with no factories, no per-user agent objects, and no way for a prompt to redirect the namespace.

Scoping happens through the namespace name, so identity enters only where you write it into that name.

## Files

- `basic.py`: the declarative common case, `namespace="assistant/{user_id}"`. One agent serves alice and bob with fully isolated files, and an anonymous run fails closed instead of collapsing into a shared store.
- `custom_factory.py`: the escape hatch for arbitrary policy. A callable tool factory builds the FileSystem from `run_context`, and here VIP users get their own tier of namespaces.
- `shared_namespace.py`: two agents share files by attaching the same namespace name. The producer writes, and the consumer attaches with `tools(read_only=True)`, which gives it four read tools and the read-only instructions and no way to write.

## When to use

- Any user-facing agent that keeps working state. Without `{user_id}` in the namespace, users share one file store.
- Role- or tenant-based scoping beyond a single placeholder: `custom_factory.py`.
- One agent producing records that another agent consults: `shared_namespace.py`.
- For the single-tenant basics first, see [`_01_getting_started/`](../_01_getting_started/). To inspect any of these namespaces from a script, see [`_05_operations/`](../_05_operations/).

## Run

```bash
python cookbook/filesystem/_04_multi_tenancy/basic.py
python cookbook/filesystem/_04_multi_tenancy/custom_factory.py
python cookbook/filesystem/_04_multi_tenancy/shared_namespace.py
```

Requires `OPENAI_API_KEY`.
