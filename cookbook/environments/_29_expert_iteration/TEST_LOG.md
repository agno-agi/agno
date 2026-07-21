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
3 conversations (the cumulative dataset dedups exact-duplicate rows, and each
task's passing attempts here are byte-identical; before dedup landed this read
6) and returned a two-step loss curve; the cumulative dataset was written to
the loop's temp workdir.

Re-run after Phase E (the `agno.trainers.tinker` module now exists): still PASS
offline, confirming the lazy SDK import is not reached when no key is set.

Re-run after the consent gate landed: with `TINKER_API_KEY` present but
`AGNO_RUN_TINKER_FINE_TUNE` unset, the file prints the capability-not-consent
notice and runs the offline stub — key presence alone no longer selects the
paid trainer. Offline output unchanged.

---

### basic.py — live path

**Status:** PARTIAL (auth + sample initiation proven; nothing scored, fine-tune blocked on network)

**Description:** With `AGNO_RUN_TINKER_FINE_TUNE=1` and `TINKER_API_KEY` set,
the same file swaps the stub for
`TinkerTrainer(base_model="Qwen/Qwen3.6-35B-A3B", epochs=1)` and performs a real
fine-tune (3 tasks, k=4, one round). That run is bounded and recorded separately rather
than as part of routine cookbook testing, because it spends real training compute.

**Result (2026-07-21):** A live sampling smoke against the real Qwen3.6-35B-A3B
authenticated and *initiated* real samples through the adapter — auth, session,
sampling client, renderer-from-tokenizer, `sample()` dispatched — but none of the 6
attempts completed within the then-default 120s per-attempt timeout, so 0/6 were
parsed or scored. That proves auth and sample initiation, not the parse/score path
end to end; it is also why the env now sets `timeout_seconds=900`. Two
subsequent attempts and a connectivity probe failed to reach the Tinker auth endpoint
(intermittent network, `APIConnectionError`, upstream of any agno code), so the one
bounded `fit` was not attempted — spending training money on a run that cannot
authenticate for the follow-on sampling would break the spend policy. Full detail and
the by-hand completion command are in `specs/agno/2.8.1/notes/live-proof.md`. Re-run by
hand from a network where the Tinker host is reachable.

---
