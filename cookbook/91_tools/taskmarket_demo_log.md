# TaskMarket toolkit demo

## Reproduction

```
pytest libs/agno/tests/unit/tools/test_taskmarket.py -q
```

## Setup

Install the official TaskMarket CLI from https://docs.taskmarket.dev/ then run `taskmarket init`.
This toolkit never stores keys.

## Live unauthenticated GET (2026-08-20)

GET https://api.taskmarket.dev/api/tasks?status=open&limit=1

Returned task `0x9092b27b323d2c11c5549527ffcc92d859cb4c09980a4b88facfdf5998d52b40`
status=open reward=2000000 (2 USDC) submissionCount=40.

This shows live status retrieval works without keys.

No real task was created or funded in this demo.
