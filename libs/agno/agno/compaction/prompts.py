"""Prompt constants for conversation compaction."""

# Marker line that opens the summary message injected into model input.
# Fixed so injected summaries are identifiable (and skippable) across builds.
SUMMARY_PREFIX = "Summary of earlier conversation (compacted):\n\n"

# Placeholder for a tool result elided from the model view. The transcript
# keeps the full result; only the view renders this line.
ELISION_PLACEHOLDER = "[tool result elided by compaction: {n_chars} chars. Re-run the tool if this result is needed.]"

DEFAULT_COMPACTION_PROMPT = """You maintain the running summary of a long conversation between a user and an AI agent. The
conversation exceeds the model's context window, so everything older than a recent tail is folded into
the summary you produce. Your summary is the ONLY memory of the folded conversation: anything you omit
is lost to the agent.

You are given the previous summary (if one exists) and a transcript segment to fold into it. Produce an
updated summary with exactly these sections:

## Goal
## Constraints & preferences
## Completed
## Key decisions & facts
## In progress / next steps
## Errors & fixes
## Critical context

Section guidance:
- Goal: what the user is ultimately trying to achieve. Rarely changes.
- Constraints & preferences: standing user constraints and instructions that remain in force — coding
  rules, limits, style and process preferences. These are easy to lose; keep every one that has not been
  explicitly lifted.
- Completed: finished work, stated compactly.
- Key decisions & facts: decisions made and why, plus durable facts established in conversation.
- In progress / next steps: what is underway and what comes next.
- Errors & fixes: errors encountered and how they were resolved (or that they remain open).
- Critical context: exact file paths, identifiers, result_ids, URLs, error messages, and numbers —
  verbatim. Never paraphrase these.

Rules:
- Preserve everything from the previous summary unless the new segment supersedes it.
- Move items that the new segment shows are finished into Completed.
- Do not continue the conversation, answer questions, or add commentary.
- Output only the summary, starting at "## Goal".
- Hard length budget: {budget_tokens} tokens. Compress prose before dropping facts.

Durable state (offloaded tool results, defined variables, files on disk) outlives this summary and is
listed separately for the agent; you do not need to reproduce its contents, only reference identifiers
in Critical context when they matter."""


# Appended to the summarization prompt when the folded messages are archived and the agent can
# read them back. A summary cannot be complete, and the agent reading it cannot tell what is
# missing unless the summary says so - which is what turns "answer from the summary" into
# "check the archive first" on exactly the questions that need it.
ARCHIVE_AWARE_PROMPT = """

The full transcript of the folded segment remains available to the agent at `{archive_path}`.
End the summary with one line beginning "Not covered here:" naming the kinds of detail a reader
would have to look up there - for example bulk tabular data, long tool output, or full error
text. Omit the line only if the summary genuinely preserves every specific in the segment."""

# Appended to the injected summary message when the archive is readable by the agent. States the
# rule rather than suggesting it: a model told to "search if needed" will usually judge the
# summary sufficient and answer from it, including for the exact values a summary is least
# likely to have kept.
ARCHIVE_LOOKUP_INSTRUCTION = """

The full text of the folded conversation is stored at `{archive_path}`.
Before answering any question about it that calls for an exact value - an identifier, figure,
name, quote, command, or error message - read or search that file rather than relying on this
summary. Say you do not know only after looking."""
