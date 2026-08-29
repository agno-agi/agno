# Context Compaction

Bounded model input over an unbounded session. When context nears the model's
window, old tool results are elided and older conversation folds into a
running summary; the stored transcript is never touched.

- `01_context_compaction.py` — `compaction=True` on a long session; the record chain.
- `02_manual_compact.py` — `agent.compact()` with focus instructions, the `/compact` analog.
- `03_compaction_events.py` — the CompactionStarted / CompactionCompleted event pair on a streamed run.
- `04_compaction_with_offload.py` — both context layers together; result ids survive the fold.

Compaction owns history retention while enabled: `num_history_runs` and
friends are ignored. It cannot be combined with `compress_tool_results`
(elision already covers it). By default passes start early and run in the
background, so the conversation never pauses for compaction.
