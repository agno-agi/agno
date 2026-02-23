# Test Log: interfaces/slack

> All examples require a live Slack workspace. Run each file and update this log.

### basic.py

**Status:** PASS

**Description:** Minimal non-streaming agent responding to @mentions with session history via SQLite. Tested with `@Agent test Hello! Testing non-streaming typing indicator` in #interfaces channel. Bot replied with a greeting. Typing indicator (`setStatus("Thinking...")`) fires before processing. Verified reply_to_mentions_only works in channel context.

---

### basic_workflow.py

**Status:** PASS

**Description:** Two-step workflow (Research Agent -> Content Writer) in Slack. Tested with `@Agent test Write a summary about the current state of autonomous vehicles in 2026`. Server logs showed both steps executing sequentially (Research Step then Writing Step). Bot posted a detailed article in the thread. Non-streaming fallback used since top-level @mentions lack thread_ts.

---

### streaming.py

**Status:** PASS

**Description:** Streaming agent with WebSearchTools. Tested with `@Agent test What is the latest news about AI agents?` in #interfaces channel. Bot responded with a well-structured numbered list of 5 news articles (TechRepublic, HBR, Business Insider, VentureBeat, MSN) with bold titles, summaries, and source links. Response streamed via `chat_stream` with proper markdown formatting. WebSearchTools executed correctly mid-stream.

---

### streaming_research.py

**Status:** PASS

**Description:** Research agent with DuckDuckGo, HackerNews, and YFinance tools. Tested with `@Agent test What are the top stories on HackerNews today?` in #interfaces channel via Cloudflare tunnel. Bot returned a well-formatted list of 10 real HackerNews stories with bold titles, source links, and descriptions. HackerNewsTools correctly fetched live data from the HN API. Response streamed via `chat_stream`.

---

### streaming_deep_research.py

**Status:** PENDING

**Description:** Deep research agent with 7 toolkits (DDG, HN, YFinance, Wikipedia, Arxiv, Calculator, Newspaper4k). Stress-tests plan display with 8-12+ concurrent tool cards.

---

### streaming_team.py

**Status:** PASS

**Description:** Stock Research Team with two members (Stock Searcher + Company Info). Tested with `@Agent test Give me a full analysis of TSLA` in #interfaces channel via Cloudflare tunnel. Coordinator delegated to both members — Stock Searcher returned live price ($396.52) and analyst recommendations (45 analysts), Company Info returned qualitative analysis and news. Response took ~2 min due to multi-agent coordination. Streamed via `chat_stream`.

---

### agent_with_user_memory.py

**Status:** PENDING

**Description:** Agent with MemoryManager that captures user name, hobbies, and preferences. Verify memories persist across conversations and personalize responses.

---

### channel_summarizer.py

**Status:** PENDING

**Description:** Agent using SlackTools to read channel history and thread replies. Verify it produces structured summaries with sections for discussions, decisions, and action items.

---

### file_analyst.py

**Status:** PENDING

**Description:** Agent that downloads Slack files via SlackTools, analyzes content (CSV, code, text), and uploads results. Requires `files:read` and `files:write` scopes.

---

### reasoning_agent.py

**Status:** PASS

**Description:** Agent with ReasoningTools and WebSearchTools using Claude Sonnet. Tested with `@Agent test Compare AAPL and MSFT stock performance this year. Which is the better investment?` in #interfaces channel via Cloudflare tunnel. ReasoningTools chain-of-thought visible (Next Action: final_answer, Confidence: 0.9). Response included markdown table with live prices (AAPL $269.21 -2.7%, MSFT $397.23 -17.42%), detailed analysis sections, and investment recommendation. Streamed via `chat_stream`.

---

### research_assistant.py

**Status:** PENDING

**Description:** Agent combining SlackTools message search (Slack query syntax) with WebSearchTools. Verify it searches internal Slack history and external web, then synthesizes findings.

---

### support_team.py

**Status:** PASS

**Description:** Multi-agent team with Technical Support and Documentation Specialist. Tested with `@Agent test How do I handle rate limiting when making API calls in Python?` in #interfaces channel via Cloudflare tunnel. Coordinator routed to Technical Support agent which responded with 6 strategies, example Python code with exponential backoff, and additional considerations (global rate limiting, token bucket). Non-streaming fallback path. Requires SSL_CERT_FILE for macOS framework Python.

---

### multiple_instances.py

**Status:** PENDING

**Description:** Two separate Slack bots on one server with per-instance tokens and URL prefixes (`/research/events`, `/analyst/events`). Verify both bots respond independently.

---

### multimodal_team.py

**Status:** PASS

**Description:** Multi-agent team with image input (GPT-4o vision) and output (DALL-E). Tested with real PNG image analysis and PDF document analysis. Requires live Slack workspace.

---

### multimodal_workflow.py

**Status:** PASS

**Description:** Parallel workflow (Visual Analysis + Web Research) followed by Creative Synthesis with DALL-E image generation. Task cards show parallel execution progress. Requires live Slack workspace.

---

### test_all.py

**Status:** PENDING

**Description:** Two apps (Dash workflow + Ace team) on one server with separate credentials. Tests workflow streaming (parallel research + synthesis) and team streaming (web search + coordination). Requires two Slack app configurations.

---

### test_streaming_events.py

**Status:** PENDING

**Description:** Switchable agent/team/workflow via `TEST_MODE` env var. Agent mode tests reasoning + tool calls; Team mode tests member coordination; Workflow mode tests Parallel + Condition steps.

---
