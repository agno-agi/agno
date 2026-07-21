# Test Log - _29_expert_iteration

Tested 2026-07-21 with `.venvs/demo/bin/python`.

### basic.py — offline path

**Status:** PASS

**Description:** Ran one full `ImprovementLoop.step()` against the inline stub
trainer and scripted models, with `TINKER_API_KEY` explicitly stripped
(`env -u TINKER_API_KEY`) to prove the offline branch is the default and the
Tinker import path stays inert. Three haiku tasks, k=4, scored by a code scorer
that checks for three non-empty lines.

**Result:** The loop closed. Baseline pass rate 0.50, tuned pass rate 1.00; all
three tasks improved by +0.50. The diff reported "env identical, policy
changed", which is the property the whole measurement rests on — same
environment fingerprint, different policy fingerprint, so the before/after is
attributable to the weights and nothing else. The stub fit reported training on
6 conversations and returned a two-step loss curve; the cumulative dataset was
written to the loop's temp workdir.

Re-run after Phase E (the `agno.trainers.tinker` module now exists): still PASS
offline, confirming the lazy SDK import is not reached when no key is set.

Re-run after the consent gate landed: with `TINKER_API_KEY` present but
`AGNO_RUN_TINKER_FINE_TUNE` unset, the file prints the capability-not-consent
notice and runs the offline stub — key presence alone no longer selects the
paid trainer. Offline output unchanged.

---

### basic.py — live path

**Status:** see `specs/agno/2.8.1/notes/live-proof.md`

**Description:** With `AGNO_RUN_TINKER_FINE_TUNE=1` and `TINKER_API_KEY` set,
the same file swaps the stub for
`TinkerTrainer(base_model="Qwen/Qwen3.6-35B-A3B", epochs=1)` and performs a real
fine-tune. That run is bounded and recorded separately rather than as part of
routine cookbook testing, because it spends real training compute.

**Result:** recorded in the live-proof note.

---
