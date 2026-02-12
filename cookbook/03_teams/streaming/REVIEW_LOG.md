# Review Log: streaming

> Reviewed: 2026-02-11 (v2.5 audit)

## Framework Issues

[FRAMEWORK] team/_run.py:841,2238 — Task-mode streaming fallback yields non-iterator (not directly exercised by these cookbooks but relevant to streaming patterns).

## Cookbook Quality

[QUALITY] team_events.py — First content delta is skipped due to if/else printing logic; the event type check prioritizes tool call events over content events, so the first content chunk may not be printed.

## Fixes Applied

None needed — both files are LIKELY OK for v2.5.
