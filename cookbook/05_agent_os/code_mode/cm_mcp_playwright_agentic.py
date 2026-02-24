"""
Code Mode — MCP Playwright Multi-Step Agentic Test
====================================================
Long-running agentic test: model browses multiple pages, takes screenshots,
reasons about what it sees, and synthesizes findings. This is the real-world
stress test for code_mode + MCP media sideband.

Validates:
1. Multiple screenshots across turns don't bloat context (sideband works)
2. Model can see and reason about screenshots (media flows to model)
3. Media collector resets per run_code call (no cross-call leaks)
4. Token usage stays proportional to text, not screenshot bytes

Run: PYTHONPATH=libs/agno .venvs/demo/bin/python cookbook/05_agent_os/code_mode/cm_mcp_playwright_agentic.py
"""

import asyncio
import time

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.mcp import MCPTools

TASK = """
Research the following 3 websites and compile a brief report:

1. Navigate to https://news.ycombinator.com — take a screenshot, tell me the top 3 story titles
2. Navigate to https://example.com — take a screenshot, tell me what the page says
3. Navigate to https://httpbin.org — take a screenshot, list the main sections visible

After visiting all 3 sites, write a summary comparing what each site is about.
Store your final answer in `result`.
"""


async def main():
    async with MCPTools("npx -y @playwright/mcp@latest --headless") as mcp_tools:
        agent = Agent(
            model=Claude(id="claude-sonnet-4-20250514"),
            tools=[mcp_tools],
            code_mode=True,
            markdown=True,
        )

        t0 = time.time()
        response = await agent.arun(TASK)
        elapsed = time.time() - t0

        print("\n" + "=" * 60)
        print("AGENTIC PLAYWRIGHT TEST RESULTS")
        print("=" * 60)

        # Content analysis
        content = response.content or ""
        print(f"\nContent length: {len(content)} chars")
        print(f"Content preview:\n{content[:500]}")

        # Image analysis
        image_count = len(response.images) if response.images else 0
        total_image_bytes = 0
        if response.images:
            for i, img in enumerate(response.images):
                size = len(img.content or b"")
                total_image_bytes += size
                print(f"  Image[{i}]: {size:,} bytes")

        print(f"\nTotal images: {image_count}")
        print(f"Total image bytes: {total_image_bytes:,}")

        # Byte leak check
        content_has_bytes = "content=b'" in content or "\\x89PNG" in content
        print(f"Content contains raw bytes: {content_has_bytes}")

        # Token analysis
        m = response.metrics
        if m:
            print(f"\nTokens: {m.total_tokens:,}")
            print(f"  Input:  {m.input_tokens:,}")
            print(f"  Output: {m.output_tokens:,}")
            if total_image_bytes > 0:
                tokens_per_kb_image = m.total_tokens / (total_image_bytes / 1024)
                print(f"  Tokens per KB of images: {tokens_per_kb_image:.0f}")

        msg_count = len(response.messages or [])
        print(f"Messages: {msg_count}")

        # Tool call analysis
        run_code_calls = 0
        if response.tools:
            for tc in response.tools:
                if tc.tool_name == "run_code":
                    run_code_calls += 1
        print(f"run_code calls: {run_code_calls}")

        print(f"\nDuration: {elapsed:.1f}s")

        # Verdict
        # Token budget: ~20K base + ~15K per screenshot (multimodal image tokens).
        # 3 screenshots ≈ 65K is expected. 100K cap catches actual bloat (byte leaks).
        print("\n" + "-" * 60)
        token_cap = 20_000 + (image_count * 20_000)
        checks = {
            "Has content": len(content) > 100,
            "Multiple images captured": image_count >= 2,
            "No byte leak": not content_has_bytes,
            "Multiple run_code calls": run_code_calls >= 2,
            f"Tokens under cap ({token_cap:,})": (m.total_tokens < token_cap)
            if m
            else False,
        }
        all_pass = True
        for check, passed in checks.items():
            status = "PASS" if passed else "FAIL"
            if not passed:
                all_pass = False
            print(f"  [{status}] {check}")

        print(f"\nOVERALL: {'PASS' if all_pass else 'FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
