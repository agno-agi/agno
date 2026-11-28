# Validation run 2026-02-15T00:39:12

## Pattern Check
**Status:** PASS
**Notes:** Passed.

## OpenAIChat references
- TEST_LOG.md

---

### custom_system_message.py

**Status:** PASS

**Description:** Cookbook execution attempt

**Result:** DEBUG ******************* Team ID: team-coach ********************              
DEBUG ***** Session ID: 3f1e6bb5-474b-4119-9a11-6e949101e73d *****              
DEBUG Creating new TeamSession: 3f1e6bb5-474b-4119-9a11-6e949101e73d            
DEBUG *** Team Run Start: 63ea0a3a-9400-4323-9166-6c5a15dab613 ***              
DEBUG Processing tools for model                                                
DEBUG Added tool delegate_task_to_member                                        
DEBUG --------------- OpenAI Response Stream Start ---------------              
DEBUG -------------------- Model: gpt-5-mini ---------------------              
DEBUG ========================== system ==========================              
DEBUG You are a performance coach for remote teams. Every answer must end with  
      one concrete next action.                                                 
DEBUG =========================== user ===========================              
DEBUG How should my team improve meeting quality this week?                     
DEBUG ======================== assistant =========================              
DEBUG Good question — small, focused changes this week can make me

---

### additional_context.py

**Status:** PASS

**Description:** Cookbook execution attempt

**Result:** DEBUG ******************* Team ID: policy-team *******************              
DEBUG ***** Session ID: a3da80ec-f0d8-4a18-a6ae-9d14a3b37523 *****              
DEBUG Creating new TeamSession: a3da80ec-f0d8-4a18-a6ae-9d14a3b37523            
DEBUG Resolving dependencies                                                    
DEBUG *** Team Run Start: 826614ab-1f73-42a3-975e-e0b91342ee52 ***              
DEBUG Processing tools for model                                                
DEBUG Added tool delegate_task_to_member                                        
DEBUG --------------- OpenAI Response Stream Start ---------------              
DEBUG -------------------- Model: gpt-5-mini ---------------------              
DEBUG ========================== system ==========================              
DEBUG You coordinate a team of specialized AI agents to fulfill the user's      
      request. Delegate to members when their expertise or tools are needed. For
      straightforward requests you can handle directly — including using your   
      own tools — respond without delegating.                                   
                                                                  

---

### introduction.py

**Status:** PASS

**Description:** Cookbook execution attempt

**Result:** DEBUG ****** Team ID: 37039468-b0b4-4330-9ab6-2757f9385fd6 *******              
DEBUG **** Session ID: introduction_session_mountain_climbing ****              
DEBUG *** Team Run Start: f40fb86b-0664-4f80-8152-240d3877014f ***              
DEBUG Processing tools for model                                                
DEBUG Added tool delegate_task_to_member                                        
DEBUG Getting messages from previous runs: 6                                    
DEBUG Adding 6 messages from history                                            
DEBUG ------------------ OpenAI Response Start -------------------              
DEBUG ---------------------- Model: gpt-5.2 ----------------------              
DEBUG ========================== system ==========================              
DEBUG You coordinate a team of specialized AI agents to fulfill the user's      
      request. Delegate to members when their expertise or tools are needed. For
      straightforward requests you can handle directly — including using your   
      own tools — respond without delegating.                                   
                                                                  

---

### few_shot_learning.py

**Status:** FAIL

**Description:** Cookbook execution attempt

**Result:** Timeout after 30s

---

### filter_tool_calls_from_history.py

**Status:** FAIL

**Description:** Cookbook execution attempt

**Result:** Timeout after 30s

---

### location_context.py

**Status:** FAIL

**Description:** Cookbook execution attempt

**Result:** Timeout after 30s

---

## Team compaction, 2026-11-28

Ran with `.venv/bin/python`, `gpt-5.6-luna` and PostgreSQL from `./cookbook/scripts/run_pgvector.sh`.

### compaction/team_compaction.py

**Status:** PASS

**Description:** A team of two members answers six questions, then `team.compact()` folds the leader's conversation and a seventh question asks for a fact from the first.

**Result:** Compacted 10 messages (1867 -> 1265 tokens, archived). The team answered that the budget was 4,000 dollars. 26 messages were still stored in the session.

---

### compaction/team_compaction_events.py

**Status:** PASS

**Description:** Five long questions on the async streamed path with a low threshold, printing the run and compaction events.

**Result:** Run with `compact_at_tokens=3_000`: each fold printed `TeamRunStarted`, `TeamCompactionStarted`, `TeamCompactionCompleted` in that order, for example 26210 -> 13486 tokens. One turn of this demo is about 13,000 tokens, so that threshold folded on every run and warned. The file now sets 20,000; it was not run again at that value.

---

### compaction/team_compaction_searchable_archive.py

**Status:** PASS

**Description:** A 30-row parts list is folded under a 150-token summary budget, then one row is asked for.

**Result:** Compacted 4 messages (793 -> 193 tokens). The leader called `search_compacted_history` with `PART-1017|1017` and answered bin F17, 88 in stock, which matches the list.

---

### compaction/team_compaction_members.py

**Status:** PASS

**Description:** A member with `add_history_to_context=True` and its own `Compaction(compact_at_tokens=2_000)` is delegated five questions.

**Result:** The member's history was folded twice (6807 -> 1234 and 2102 -> 1338 tokens). Both records carry `owner_id=researcher`. The leader's threshold of 100,000 was not reached, so it has no record.

---
