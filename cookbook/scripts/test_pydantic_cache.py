"""
Test that tool cache works when a tool returns a Pydantic model (issue #6676).
Run: .venv/bin/python cookbook/scripts/test_pydantic_cache.py
"""
import tempfile
from pathlib import Path

from pydantic import BaseModel

from agno.tools import tool
from agno.tools.function import FunctionCall

# Unique cache dir per run so we start with empty cache
CACHE_DIR = Path(tempfile.mkdtemp(prefix="agno_test_pydantic_cache_"))


class OrderResponse(BaseModel):
    success: bool
    data: dict | None = None


call_count = 0


def get_order_impl(order_id: int) -> OrderResponse:
    """Get order by ID."""
    global call_count
    call_count += 1
    return OrderResponse(success=True, data={"id": order_id, "status": "delivered"})


get_order = tool(cache_results=True, cache_ttl=300, cache_dir=str(CACHE_DIR))(get_order_impl)


def main():
    global call_count
    # get_order is a Function (returned by @tool decorator)

    call1 = FunctionCall(function=get_order, arguments={"order_id": 12345})
    call_count = 0
    print("First call (should execute function)...")
    r1 = call1.execute()
    first_count = call_count
    print("  call_count after first run:", first_count, " result:", r1.result)

    call2 = FunctionCall(function=get_order, arguments={"order_id": 12345})
    print("Second call with same args (should hit cache)...")
    r2 = call2.execute()
    second_count = call_count
    print("  call_count after second run:", second_count, " result:", r2.result)

    if first_count == 1 and second_count == 1:
        print("PASS: Second call used cache (function ran only once).")
    else:
        print("FAIL: Function ran", second_count, "times; expected 1 (cache hit).")

    import shutil

    shutil.rmtree(CACHE_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
