"""Worker capacity follows actual work, including after caller cancellation."""

from __future__ import annotations

import asyncio
import contextvars
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Callable


class WorkBudget:
    def __init__(self, seconds: float):
        self.deadline = time.monotonic() + seconds
        self.cancelled = threading.Event()

    def remaining(self) -> float:
        if self.cancelled.is_set():
            raise asyncio.CancelledError()
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("operation_deadline")
        return remaining


class BoundedWorkers:
    def __init__(self, capacity: int, name: str):
        self._capacity = threading.BoundedSemaphore(capacity)
        self._executor = ThreadPoolExecutor(max_workers=capacity, thread_name_prefix=name)

    @staticmethod
    def _execute(context, fn, args, kwargs, budget):
        try:
            return context.run(fn, *args, budget=budget, **kwargs)
        except asyncio.CancelledError:
            if budget.cancelled.is_set():
                # The waiting caller has already observed cancellation/timeout.
                # Complete the worker normally after its resource cleanup, avoiding
                # an abandoned CancelledError on the asyncio future bridge.
                return None
            raise

    def run_sync(self, fn: Callable[..., Any], *args: Any, seconds: float, **kwargs: Any) -> Any:
        if not self._capacity.acquire(blocking=False):
            raise TimeoutError("worker_capacity")
        budget = WorkBudget(seconds)
        context = contextvars.copy_context()
        try:
            future = self._executor.submit(self._execute, context, fn, args, kwargs, budget)
        except BaseException:
            self._capacity.release()
            raise
        future.add_done_callback(lambda _: self._capacity.release())
        try:
            return future.result(timeout=seconds)
        except FutureTimeoutError as exc:
            budget.cancelled.set()
            raise TimeoutError("operation_deadline") from exc
        except BaseException:
            budget.cancelled.set()
            raise

    async def run(self, fn: Callable[..., Any], *args: Any, seconds: float, **kwargs: Any) -> Any:
        if not self._capacity.acquire(blocking=False):
            raise TimeoutError("worker_capacity")
        budget = WorkBudget(seconds)
        context = contextvars.copy_context()
        try:
            future = self._executor.submit(self._execute, context, fn, args, kwargs, budget)
        except BaseException:
            self._capacity.release()
            raise
        future.add_done_callback(lambda _: self._capacity.release())
        wrapped = asyncio.wrap_future(future)
        # Retrieve abandoned exceptions without cancelling a worker's completion accounting.
        wrapped.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            return await asyncio.wait_for(asyncio.shield(wrapped), timeout=seconds)
        except asyncio.TimeoutError as exc:
            budget.cancelled.set()
            raise TimeoutError("operation_deadline") from exc
        except (asyncio.CancelledError, TimeoutError):
            budget.cancelled.set()
            raise
