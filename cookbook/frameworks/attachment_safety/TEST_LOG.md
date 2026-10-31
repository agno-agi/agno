# Test log

### test_media_staging_safety.py

**Status:** PASS

**Description:** Deterministic filesystem regressions for partial writes, rollback,
run-ID traversal, symlink paths, historical-root relocation and failures restoring
prior inputs in Claude/Codex wrappers, with and without retained uploads.

**Result:** 24 cases passed without model or hosted-provider calls. The full external-agent unit suite passed 515 cases (one expected deprecation warning).
Both required formatting and validation scripts passed in the established
`claude-dx-validation` environment. No live model or hosted-provider calls were made.

---

### Review follow-ups (2026-10-11)

**Status:** PASS (claude-sonnet-4-6; openai-codex 0.161.0 with gpt-5.6-luna)

**Description:** Replicated the two claims against `main` and this branch: a failing second attachment, and a session resumed on a replica with a different workspace. Then the media cookbooks for both harnesses and an AgentOS multipart upload on this branch. Edge checks: a file the harness writes next to a staged input, a symlinked workspace path, and a symlinked uploads directory with `retries=2`.

**Result:** On `main` the first attachment and its folders were left behind when the second failed, and the other replica wrote the restored file into the first replica's directory; on this branch nothing is left behind and the file is restored under the active workspace with the relocation note, which Claude followed with a `Read`. Cookbooks and the upload path pass with no leftover under the workspace. Two follow-ups fixed here: the new per-file cleanup left a run folder behind when the harness wrote beside the inputs (the folder is removed whole again when the turn created it), and a staging rejection was retried as a transient error (now an input check error, one attempt).

---

### attachment_staging.py (2026-10-11)

**Status:** PASS (claude-sonnet-4-6)

**Description:** Live cookbook for the four guarantees: a simulated write failure on the second attachment, a session continued on a replica with a different workspace, a file Claude writes beside the attachment with the Write tool, and a symlinked uploads directory with `retries=2`. Each case reports on its own so an older build shows which guarantees it lacks.

**Result:** Nothing left after the failed staging; replica B read the restored file from its own workspace (`Read` on `replica-b/.agno/uploads/<run>/notes.txt`) and nothing was written under replica A; Claude's `upper.txt` went with the run folder; the symlink case ended ERROR after one attempt with `retryable: False` and `error_type: input_check_error`, and nothing was written into the linked directory.

---

