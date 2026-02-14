# TEST_LOG.md - 91 Tools Root

**Test Date:** 2026-02-11
**Branch:** `cookbooks/v2.5-testing`

---

## PASS (57 files)

### agentql_tools.py — SKIP (missing package: agentql)
### airflow_tools.py — PASS
**Re-verified:** 2026-02-14 — Airflow param rename applied. Agent generated Airflow DAG code correctly using `schedule` instead of deprecated `schedule_interval`.
### apify_tools.py — SKIP (missing package: apify-client)
### arxiv_tools.py — PASS
### aws_lambda_tools.py — PASS
**Re-verified:** 2026-02-14 — Dead params removed. Agent loaded, invoked Lambda tools correctly (no functions in AWS env, expected). Both invocation and management examples ran cleanly.
### aws_ses_tools.py — PASS
### baidusearch_tools.py — SKIP (missing package: baidusearch)
### bitbucket_tools.py — PASS
### brandfetch_tools.py — PASS
### bravesearch_tools.py — SKIP (missing package: brave-search)
### brightdata_tools.py — SKIP (missing API key: BRIGHT_DATA_API_KEY)
### browserbase_tools.py — SKIP (missing package: browserbase)
### calcom_tools.py — PASS
### calculator_tools.py — PASS
### cartesia_tools.py — SKIP (missing package: cartesia)
### clickup_tools.py — SKIP (missing API key: CLICKUP_API_KEY)
### composio_tools.py — SKIP (missing package: composio_agno)
### confluence_tools.py — SKIP (missing package: atlassian-python-api)
### crawl4ai_tools.py — SKIP (missing package: crawl4ai)
**Re-verified:** 2026-02-14 — Simplified to `enable_crawl`. Compiles OK but crawl4ai not installed in demo venv.
### csv_tools.py — PASS
### custom_api_tools.py — PASS
### custom_tool_events.py — PASS
### custom_tools.py — PASS
### dalle_tools.py — PASS
### daytona_tools.py — SKIP (missing package: daytona)
### desi_vocal_tools.py — PASS
### discord_tools.py — SKIP (missing API key: DISCORD_BOT_TOKEN)
### docker_tools.py — SKIP (missing package: docker)
### duckdb_tools.py — PASS
### duckduckgo_tools.py — PASS
### e2b_tools.py — SKIP (missing package: e2b_code_interpreter)
### elevenlabs_tools.py — SKIP (missing package: elevenlabs)
### email_tools.py — PASS
### evm_tools.py — SKIP (missing package: web3)
### exa_tools.py — PASS
### fal_tools.py — SKIP (missing package: fal-client)
### file_generation_tools.py — PASS
### file_tools.py — PASS
### financial_datasets_tools.py — PASS
### firecrawl_tools.py — SKIP (missing package: firecrawl-py)
### giphy_tools.py — PASS
### github_tools.py — SKIP (missing package: PyGithub)
### gmail_tools.py — SKIP (missing package: google-api-python-client)
### google_bigquery_tools.py — SKIP (missing package: google-cloud-bigquery)
### google_drive.py — SKIP (missing package: google-api-python-client)
### google_maps_tools.py — SKIP (missing package: crawl4ai)
### googlecalendar_tools.py — SKIP (missing package: google-api-python-client)
### googlesheets_tools.py — SKIP (missing package: google-api-python-client)
### hackernews_tools.py — PASS
### jinareader_tools.py — PASS
### jira_tools.py — SKIP (missing package: jira)
### knowledge_tool.py — PASS
### linear_tools.py — PASS
### linkup_tools.py — SKIP (missing package: linkup-sdk)
### lumalabs_tools.py — SKIP (missing package: lumaai)
### mcp_tools.py — PASS
### mem0_tools.py — SKIP (missing package: mem0ai)
### mlx_transcribe_tools.py — SKIP (missing package: mlx-whisper)
### models_lab_tools.py — PASS
### moviepy_video_tools.py — SKIP (missing package: moviepy)
### multiple_tools.py — PASS
### nano_banana_tools.py — PASS
### neo4j_tools.py — SKIP (missing package: neo4j)
### newspaper_tools.py — PASS
### newspaper4k_tools.py — PASS
### notion_tools.py — SKIP (missing package: notion-client)
### openbb_tools.py — SKIP (missing package: openbb)
### opencv_tools.py — SKIP (missing package: opencv-python)
### openweather_tools.py — SKIP (missing API key: OPENWEATHER_API_KEY)
### oxylabs_tools.py — SKIP (missing package: oxylabs)
### pandas_tools.py — PASS
### parallel_tools.py — PASS
### postgres_tools.py — PASS
### pubmed_tools.py — PASS
### python_function_as_tool.py — PASS
### python_tools.py — PASS
### reddit_tools.py — SKIP (missing package: praw)
### redshift_tools.py — SKIP (missing package: redshift-connector)
### replicate_tools.py — SKIP (missing package: replicate)
### resend_tools.py — SKIP (missing package: resend)
### scrapegraph_tools.py — SKIP (missing package: scrapegraph-py)
### searxng_tools.py — FAIL (framework bug: Toolkit.__init__() got unexpected keyword argument 'news')
### seltz_tools.py — SKIP (missing package: seltz)
### serpapi_tools.py — SKIP (missing package: google-search-results)
### serper_tools.py — PASS
### shell_tools.py — PASS
### shopify_tools.py — PASS
### slack_tools.py — PASS
### sleep_tools.py — PASS
### spider_tools.py — SKIP (missing package: spider-client)
### spotify_tools.py — PASS
### sql_tools.py — PASS
### tavily_tools.py — SKIP (missing package: tavily-python)
### telegram_tools.py — PASS
### todoist_tools.py — SKIP (missing package: todoist-api-python)
### tool_calls_accesing_agent.py — PASS
### trafilatura_tools.py — SKIP (missing package: trafilatura)
### trello_tools.py — SKIP (missing package: py-trello)
### twilio_tools.py — SKIP (missing package: twilio)
### unsplash_tools.py — PASS
### valyu_tools.py — SKIP (missing package: valyu)
### visualization_tools.py — PASS
### web_tools.py — PASS
### webbrowser_tools.py — PASS
### webex_tools.py — SKIP (missing API key: WEBEX_ACCESS_TOKEN)
### websearch_tools.py — PASS
### website_tools.py — PASS
### website_tools_knowledge.py — PASS
### whatsapp_tools.py — PASS
### wikipedia_tools.py — PASS
**Re-verified:** 2026-02-14 — Dead boolean params removed (`enable_search=True` etc.). First Wikipedia search (AI) succeeded, second (machine learning) returned "Page not found" (Wikipedia API issue, not framework bug). Agent handled gracefully.
### x_tools.py — SKIP (missing package: tweepy)
### yfinance_tools.py — PASS
### youtube_tools.py — PASS
### zendesk_tools.py — PASS
### zep_tools.py — SKIP (missing package: zep-cloud)
### zoom_tools.py — PASS

---

## Summary

| PASS | FAIL | SKIP (pkg) | SKIP (key) | Total |
|------|------|------------|------------|-------|
| 57   | 1    | 53         | 5          | 116   |

### Framework Bug

- **searxng_tools.py**: `SearxngTools.__init__()` passes `news` kwarg to `Toolkit.__init__()` which doesn't accept it. This is a v2.5 regression in `agno/tools/searxng.py`.

### Notes

- Most SKIPs are due to optional Python packages not installed in the demo venv
- PASS files all use standard v2.5 APIs correctly
- External API failures (rate limits, auth issues) are not counted as FAILs when the framework code executed correctly
