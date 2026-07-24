# Test Log - _02_durable_records

Tested 2026-07-24 against `gpt-5.5` (OpenAIResponses), agno 2.8.0 (source tree, branch feat/agent-fs).
Re-run fresh at the final sweep (same date): every file in this folder PASS.

### basic.py

**Status:** PASS

**Description:** The dedupe loop over two overlapping ticket batches: check_lines with directory='seen' before acting, append_file after, second pass acts only on the new ticket.

**Result:** Pass 1 triaged TICKET-101 and TICKET-102 and recorded them. Pass 2 replied "Triaged this run: TICKET-103. Skipped as already done: TICKET-101, TICKET-102." Record log after both passes contained exactly three lines: TICKET-101, TICKET-102, TICKET-103.

---

### radar_news_delta.py

**Status:** PASS

**Description:** The flagship scheduled news-brief agent run twice over an expanding feed (3 stories, then the same 3 plus 2 new); date-partitioned seen/ files; run 2 must brief only the delta.

**Result:** Run 1 briefed all three Monday stories. Run 2 checked the five ids with check_lines and briefed exactly the two new ones: "Acme adds hybrid search to its vector database." and "Nimbus launches a spot-GPU cloud for fine-tuning." The date-partitioned log listed `seen/2026-07-24.md` containing all five ids, one per line (acme-ships-vector-db, meridian-raises-b, kite-os-release, acme-adds-hybrid-search, nimbus-gpu-cloud).

---
