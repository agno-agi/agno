# Namespaces

A namespace names the file store an agent uses. You do not need one to start: everywhere else in this cookbook the default store is fine, and `FileSystem(db)` uses it. Name one when you need more than one store in the same backend, which in practice means isolating users or deliberately sharing between agents.

Namespaces are lowercase and URL-safe, so `BANK`, `bank` and `BaNk` are one store. Same backend plus same name means the same files; a different name means full isolation. Sharing is explicit, by name.

The main reason to reach for one is per-user (and per-team) file stores from a single static agent. Put a `user_id` on the run and users get isolated files, with no factories, no per-user agent objects, and no way for a prompt to redirect the namespace. Isolation is per normalized name: since namespaces are lowercased, user ids that differ only by case (`Alice` and `alice`) land in the same store, so normalize ids upstream if your identity system treats those as two people. Identity enters only where you write it into the name.

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
python cookbook/filesystem/_04_namespaces/basic.py
python cookbook/filesystem/_04_namespaces/custom_factory.py
python cookbook/filesystem/_04_namespaces/shared_namespace.py
```

Requires `OPENAI_API_KEY`.
