# Test Log - _29_expert_iteration

Tested 2026-07-21 with `.venvs/demo/bin/python`.

### basic.py — offline path, trainer-selection rework (2026-07-22, feat/fireworks-adapter)

**Status:** PASS

**Description:** Re-ran the offline loop after making the trainer selectable
(`AGNO_TRAINER=stub|tinker|fireworks` plus the generalized consent flag
`AGNO_RUN_FINE_TUNE=1`), with all keys explicitly stripped
(`env -u TINKER_API_KEY -u FIREWORKS_API_KEY`). Also fixed the inline
`StubTrainer` to digest the real dataset bytes: the loop's provenance guard now
(correctly) refuses a checkpoint whose `dataset_digest` does not match the file
it trained on, which the old hard-coded `"offline"` digest tripped.

**Result:** The loop closed. Baseline pass rate 0.50, tuned pass rate 1.00; all
three tasks improved by +0.50 and the diff reported "env identical, policy
changed". Consent gates verified: (1) both keys present with no opt-in prints
the capability-not-consent notice and runs the stub; (2) `AGNO_TRAINER=fireworks`
without `AGNO_RUN_FINE_TUNE=1` raises before any client is built; (3)
`AGNO_TRAINER=fireworks AGNO_RUN_FINE_TUNE=1` without `FIREWORKS_API_KEY`
raises naming the missing key. No network call is reachable on any offline
path.

Re-run after the adversarial-review fold (same day): still PASS, identical
numbers. Two review findings changed this file's behavior and were re-verified:
an unmeasured round (e.g. a live baseline where every attempt times out) now
prints a legible "round measured nothing" report instead of crashing on a None
train_result, and a stale AGNO_RUN_TINKER_FINE_TUNE=1 export now conflicts
loudly with an explicit different AGNO_TRAINER instead of silently selecting a
paid Tinker run.

---

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

**Status:** see `specs/agno/2.8.3/notes/live-proof.md`

**Description:** With `AGNO_RUN_TINKER_FINE_TUNE=1` and `TINKER_API_KEY` set,
the same file swaps the stub for
`TinkerTrainer(base_model="Qwen/Qwen3.6-35B-A3B", epochs=1)` and performs a real
fine-tune. That run is bounded and recorded separately rather than as part of
routine cookbook testing, because it spends real training compute.

**Result:** recorded in the live-proof note.

---

### basic.py — live path, Fireworks

**Status:** NOT RUN (owner-gated)

**Description:** With `AGNO_TRAINER=fireworks`, `AGNO_RUN_FINE_TUNE=1`,
`FIREWORKS_API_KEY` and `FIREWORKS_ACCOUNT_ID` set, the same file runs
`FireworksTrainer(base_model="accounts/fireworks/models/qwen3-8b", epochs=1)`:
a managed LoRA SFT job (~pennies at $0.50/1M training tokens), then one
on-demand BF16 deployment with addons enabled serving both base and tuned
(order $7/hour of GPU time while serving; `teardown()` deletes it at the end of
the run). Readiness notes in `specs/agno/2.8.3/notes/FIREWORKS_BUILD.md`.

**Result:** deliberately not executed in this pass — the paid run is the
owner's step.

---
