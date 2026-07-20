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

**Status:** PARTIAL (sampling proven, fine-tune blocked on network)

**Description:** With `AGNO_RUN_TINKER_FINE_TUNE=1` and `TINKER_API_KEY` set,
the same file swaps the stub for
`TinkerTrainer(base_model="Qwen/Qwen3.6-35B-A3B", epochs=1)` and performs a real
fine-tune (3 tasks, k=4, one round). That run is bounded and recorded separately rather
than as part of routine cookbook testing, because it spends real training compute.

**Result (2026-07-21):** A live sampling smoke against the real Qwen3.6-35B-A3B
authenticated and sampled through the adapter end to end (the §3 live path works), but
was slow enough — minutes per 2000-token thinking sample — that the default 120s
per-attempt timeout was hit, which is why the env now sets `timeout_seconds=900`. Two
subsequent attempts and a connectivity probe failed to reach the Tinker auth endpoint
(intermittent network, `APIConnectionError`, upstream of any agno code), so the one
bounded `fit` was not attempted — spending training money on a run that cannot
authenticate for the follow-on sampling would break the spend policy. Full detail and
the by-hand completion command are in `specs/agno/2.8.1/notes/live-proof.md`. Re-run by
hand from a network where the Tinker host is reachable.

---

### basic.py — live path, Fireworks

**Status:** PASS (ran live, 2026-07-22) — the loop closed on open weights.

**Description:** With `AGNO_TRAINER=fireworks`, `AGNO_RUN_FINE_TUNE=1`,
`FIREWORKS_API_KEY` and `FIREWORKS_ACCOUNT_ID` set, the same file runs
`FireworksTrainer(base_model="accounts/fireworks/models/qwen3-4b-instruct-2507",
epochs=1, sampling_reasoning_effort="none")`: a managed LoRA SFT job (~pennies at
$0.50/1M training tokens), then one on-demand BF16 deployment with addons enabled
serving both base and tuned (order $7/hour of GPU time while serving; `teardown()`
deletes it at the end of the run).

**Result:** one bounded managed SFT job (1 epoch, 21 rows, never retried) moved the
pass rate on the real 5-7-5 verifier from **baseline 0.333 to tuned 0.548**
(14/42 -> 23/42, same deployment, same H100/BF16, 42/42 scored both sides); per-task
highlights `debugger_3am` 2/6 -> 6/6, `prod_friday` 1/6 -> 4/6. Teardown verified 0
deployments / 0 deployedModels left. Full narrative, the base-vs-tuned haiku, the five
live-surfaced adapter fixes, and cost are in `specs/agno/2.8.3/notes/live-proof.md`.

---
