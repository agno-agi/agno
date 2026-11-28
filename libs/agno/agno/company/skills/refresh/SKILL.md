---
name: refresh
description: Refresh Goal status from current work and source evidence.
---

Read the Goal identified in the message. Read its playbook,
then call refresh_company_goal for that Goal. This applies its archive
window (metadata.archive_window_days, default 14) and returns Project completion
proposals saved in the wiki. It never completes a Project. Present those proposals
for a human to accept through the Project transition API; never transition directly.
Read the remaining Projects and Tasks, then inspect configured Sources with read_goal_source.
Reflect observed progress and failures in status.md using its current version.
On a conflict, read again and incorporate intervening changes. Propose changes
for human review; never accept work or mark a Task Ready or Done.
Remove references to archived work from status.md so it no longer enters executor
context. Keep brief.md and status.md; maintenance only deletes recognized generated
pages older than the window. If nothing changed, return a quiet successful check
without writing duplicate pages. Report a maintenance failure instead of claiming success.

For each Source, call read_goal_source without path for a paged, content-free
index. Use pattern and next_offset to narrow discovery. Pass a returned path to
read one document; next_content_offset continues large documents. Compare the
full-document content_hash across fragments and reread if it changes. Never infer
content from an index entry. Use intake_goal_source for Task proposals;
propose_company_task is unavailable to Routines.
