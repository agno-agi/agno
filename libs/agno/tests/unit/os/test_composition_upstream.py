"""Regression cases for the exact extracted upstream proposal, Python stdlib only."""

import asyncio
import contextvars
import unittest
from contextlib import asynccontextmanager

from agno.os.app import _combine_app_lifespans as combine


class CompositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_and_single_identity(self):
        async with combine([])(None) as state:
            self.assertIsNone(state)

        @asynccontextmanager
        async def single(app):
            yield {"kept": True}

        self.assertIs(combine([single]), single)
        async with combine([single])(None) as state:
            self.assertEqual(state, {"kept": True})

    async def test_multiple_state_contract_unchanged(self):
        @asynccontextmanager
        async def state(app):
            yield {"not_merged_in_agno": True}

        async with combine([state, state])(None) as result:
            self.assertIsNone(result)

    async def exercise(self, scenario):
        events = []
        var = contextvars.ContextVar("regression", default=None)

        def resource(name):
            @asynccontextmanager
            async def context(app):
                if name == "c" and scenario == "startup":
                    raise ValueError("startup")
                token = var.set(name)
                events.append("enter:" + name)
                try:
                    yield
                except ValueError:
                    if scenario != "suppress" or name != "c":
                        raise
                finally:
                    await asyncio.sleep(0)
                    self.assertEqual(var.get(), name)
                    var.reset(token)
                    events.append("exit:" + name)
                    if name == "b" and scenario == "cleanup":
                        raise RuntimeError("cleanup")

            return context

        error = None
        try:
            async with combine([resource(n) for n in "abc"])(None):
                if scenario in ("body", "suppress"):
                    raise ValueError("body")
                if scenario == "cancel":
                    asyncio.get_running_loop().call_soon(asyncio.current_task().cancel)
                    await asyncio.sleep(1)
        except (ValueError, RuntimeError, asyncio.CancelledError) as exc:
            error = (type(exc).__name__, str(exc))
        expected = {
            "startup": ("ValueError", "startup"),
            "body": ("ValueError", "body"),
            "cleanup": ("RuntimeError", "cleanup"),
            "cancel": ("CancelledError", ""),
        }.get(scenario)
        self.assertEqual(error, expected)
        names = "ab" if scenario == "startup" else "abc"
        self.assertEqual(events, ["enter:" + n for n in names] + ["exit:" + n for n in reversed(names)])
        self.assertIsNone(var.get())

    async def test_normal(self):
        await self.exercise("normal")

    async def test_body_error(self):
        await self.exercise("body")

    async def test_startup_error(self):
        await self.exercise("startup")

    async def test_cleanup_error(self):
        await self.exercise("cleanup")

    async def test_suppression(self):
        await self.exercise("suppress")

    async def test_cancellation(self):
        await self.exercise("cancel")


if __name__ == "__main__":
    unittest.main(verbosity=2)
