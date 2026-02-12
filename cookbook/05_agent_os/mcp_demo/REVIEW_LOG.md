# Review Log — mcp_demo/

## Framework Issues

[FRAMEWORK] agno/tools/mcp/mcp.py:165 — When `env` dict contains None values (from `getenv()` for missing keys), `StdioServerParameters` raises a pydantic validation error. Should filter None values or provide a clearer error message.

## Cookbook Quality

[QUALITY] mcp_tools_advanced_example.py — Crashes at import time when BRAVE_API_KEY is missing. Should handle missing env vars gracefully or document the requirement more prominently.

## Fixes Applied

(none needed)
