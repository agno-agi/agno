# Persistence

Pass `fs=` and CodeMode pickles each top-level variable independently into AgentFS after every successful cell, debounced. One unpicklable socket is skipped and reported rather than aborting the whole snapshot.

The caps (`max_variable_bytes`, `max_snapshot_bytes`) count stored bytes — payloads are base64, four stored bytes for every three pickle bytes — and are lowered at setup to the store's own `max_file_bytes` / `max_namespace_bytes`, with one warning naming what changed. A variable that does not fit is reported by name with its size and the limit, never as unpicklable.

The database is the state: nothing about resume depends on a container's disk surviving.

- `basic.py` — variables survive a deliberate kernel kill and come back, with the `<code_mode_restored>` notice telling the model what it has.
- `developer_surface.py` — no model needed: `run`, `variables`, `value`, `shutdown` (each with an `a`-prefixed async twin).

Restore ordering is load-bearing: variables restore **before** the bootstrap cell that rebinds live toolkit handles, so a stale pickled handle always loses to this run's live one. The restore notice is emitted only after bootstrap succeeds.
