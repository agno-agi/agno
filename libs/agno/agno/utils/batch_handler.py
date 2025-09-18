import asyncio

import inspect
from typing import Any, AsyncGenerator, AsyncIterable, AsyncIterator, Callable, Coroutine, Generic, Iterable, TypeVar
import uuid
import anyio
from pydantic import BaseModel
from agno.utils.log import logger

ReturnType = TypeVar("ReturnType")
ReturnWithType = TypeVar("ReturnWithType")


class AsyncFunctionCall(BaseModel, Generic[ReturnType, ReturnWithType]):
    coroutine: Callable[..., Coroutine[Any, Any, ReturnType]]
    params: tuple[Any, ...]
    return_with: ReturnWithType
    name: str | None = None


class ReturnResult(BaseModel, Generic[ReturnType], arbitrary_types_allowed=True):
    result: ReturnType | None = None
    exception: Exception | None = None

    @property
    def is_error(self) -> bool:
        return self.error_message is not None

    @property
    def is_success(self) -> bool:
        return self.is_error is False

    @property
    def error_message(self) -> str | None:
        return str(self.exception) if self.exception else None


class BatchRunner(Generic[ReturnType, ReturnWithType]):
    def __init__(
        self, task_group_id: str | None = None, batch_size: int | None = None, batch_timeout: int | None = None
    ):
        self.task_group_id = task_group_id or str(uuid.uuid4())
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self._tasks: list[AsyncFunctionCall[ReturnType, ReturnWithType]] = []

    def add(
        self, func: Callable[..., Coroutine[Any, Any, ReturnType]], *params: Any, return_with: ReturnWithType
    ) -> None:
        self._tasks.append(AsyncFunctionCall(coroutine=func, params=params, return_with=return_with))

    async def run_as_iterator(
        self,
        raise_on_no_tasks: bool = True,
        individual_task_timeout: int | None = None,
        capture_exceptions: bool = True,
    ) -> AsyncGenerator[tuple[ReturnResult[ReturnType], ReturnWithType], None]:
        if not self._tasks:
            if raise_on_no_tasks:
                raise ValueError("No tasks to run")
            return

        concurrency = self.batch_size or len(self._tasks)

        # allow bursts so producer doesn't block if many complete at once
        send_stream, receive_stream = anyio.create_memory_object_stream(max_buffer_size=len(self._tasks))

        async def runner() -> None:
            try:
                semaphore = anyio.Semaphore(concurrency)

                async def _send_ok(value, return_with):
                    await send_stream.send((ReturnResult(result=value), return_with))

                async def _send_err(exc: Exception, return_with):
                    await send_stream.send((ReturnResult(exception=exc), return_with))

                async def process_task(task: AsyncFunctionCall[ReturnType, ReturnWithType]) -> None:
                    async with semaphore:
                        try:
                            # Call the task once to get either:
                            #  - an async iterator/generator (stream many)
                            #  - an awaitable (single result)
                            obj = task.coroutine(*task.params)

                            # Helper: whole-task timeout wrapper
                            async def run_with_whole_timeout(coro_like):
                                if individual_task_timeout:
                                    with anyio.move_on_after(individual_task_timeout) as scope:
                                        return await coro_like
                                    if scope.cancel_called:
                                        raise TimeoutError("Task timed out")
                                else:
                                    return await coro_like

                            # Case 1: streaming (async generator / async iterator)
                            if inspect.isasyncgen(obj) or isinstance(obj, (AsyncIterator, AsyncIterable)):
                                # We treat the *entire* stream as one timed operation (optional)
                                async def _drain_stream():
                                    async for item in obj:
                                        await _send_ok(item, task.return_with)

                                try:
                                    await run_with_whole_timeout(_drain_stream())
                                except Exception as e:
                                    if capture_exceptions:
                                        await _send_err(e, task.return_with)
                                    else:
                                        raise
                                return

                            # Case 2: single-result awaitable
                            try:
                                result = await run_with_whole_timeout(obj)
                                await _send_ok(result, task.return_with)
                            except Exception as e:
                                if capture_exceptions:
                                    await _send_err(e, task.return_with)
                                else:
                                    raise

                        except Exception as e:
                            # Last-resort safety
                            if capture_exceptions:
                                await _send_err(e, task.return_with)
                            else:
                                raise

                # launch all tasks; semaphore caps parallelism
                async with anyio.create_task_group() as tg:
                    for task in self._tasks:
                        tg.start_soon(process_task, task)
            finally:
                # producer signals end-of-stream
                logger.exception("Error in batch runner")
                await send_stream.aclose()

        # Move to background to avoid blocking the main thread
        background_task = asyncio.create_task(runner())

        try:
            async with receive_stream:
                async for item in receive_stream:
                    yield item
        finally:
            logger.exception("Error in batch runner")
            background_task.cancel()
            try:
                await background_task
            except Exception:
                pass

    async def _run_task(self, task: AsyncFunctionCall[ReturnType, ReturnWithType]) -> ReturnType:
        return await task.coroutine(*task.params)
