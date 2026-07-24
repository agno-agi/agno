# Test Log - _02_durable_records

Tested 2026-07-24 against `gpt-5.5` (OpenAIResponses), agno 2.8.1 (source tree, branch feat/agent-fs at 7df2fad3a).
Re-run fresh at the final sweep (same date): every file in this folder PASS.
Entries quote tool calls and printed state. Model prose varies run to run and is paraphrased rather than quoted.

### basic.py

**Status:** PASS

**Description:** The dedupe loop over two overlapping ticket batches: check_lines with directory='seen' before acting, append_file after, second pass acts only on the new ticket.

**Result:** Pass 1 called `check_lines(lines=['TICKET-101', 'TICKET-102'], directory=seen)` then `append_file(path=seen/2026-07-24.md, content=TICKET-101\nTICKET-102)`. Pass 2 called `check_lines(lines=['TICKET-101', 'TICKET-102', 'TICKET-103'], directory=seen)` then `append_file(path=seen/2026-07-24.md, content=TICKET-103)`, appending only the new id, and reported 101 and 102 as already done. The printed record log contained exactly three lines: TICKET-101, TICKET-102, TICKET-103, with no duplicates.

---

### radar_news_delta.py

**Status:** PASS

**Description:** A scheduled news-brief agent run twice over an expanding feed (3 stories, then the same 3 plus 2 new); date-partitioned seen/ files; run 2 must brief only the delta.

**Result:** Run 1 (session `radar-monday`) called `check_lines` on the three Monday ids and appended all three, then briefed three bullets. Run 2 (session `radar-tuesday`, a distinct session, so nothing carried in session state) called `check_lines(lines=['acme-ships-vector-db', 'meridian-raises-b', 'kite-os-release', 'acme-adds-hybrid-search', 'nimbus-gpu-cloud'], directory=seen)` and appended only `acme-adds-hybrid-search` and `nimbus-gpu-cloud`, briefing exactly those two and re-reporting none of the first three. The printed log listed `seen/2026-07-24.md` holding all five ids, one per line, in feed order.

---
