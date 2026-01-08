import json
import asyncio
from typing import Any, List
from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    import cognee
except ImportError:
    raise ImportError("`cognee` package not found. Please install it with `pip install cognee`")


class CogneeTools(Toolkit):
    def __init__(self, **kwargs):
        tools: List[Any] = [self.add_memory, self.search_memory]
        super().__init__(name="cognee_tools", tools=tools, **kwargs)

        self._add_lock = asyncio.Lock()
        self._add_queue: asyncio.Queue[str] = asyncio.Queue()
        log_debug("Initialized Cognee tools.")

    async def _enqueue_add(self, data: str):
        """Queue data for batch processing to maintain consistency."""
        if self._add_lock.locked():
            await self._add_queue.put(data)
            return

        async with self._add_lock:
            await self._add_queue.put(data)
            while True:
                try:
                    next_data = await asyncio.wait_for(
                        self._add_queue.get(), timeout=2
                    )
                    self._add_queue.task_done()
                except asyncio.TimeoutError:
                    break
                await cognee.add(next_data)
            await cognee.cognify()

    def add_memory(self, content: str) -> str:
        """
        Store information in the knowledge graph for future retrieval if it is not already present.
        If the information is already present, do not add it again.
        """
        try:
            if not isinstance(content, str):
                content = str(content)

            log_debug(f"Adding memory: {content}")

            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._enqueue_add(content))
                return json.dumps({"status": "success", "message": "Memory added successfully"})
            else:
                loop.run_until_complete(self._enqueue_add(content))
                return json.dumps({"status": "success", "message": "Memory added successfully"})

        except Exception as e:
            log_error(f"Error adding memory: {e}")
            return f"Error adding memory: {e}"

    def search_memory(self, query: str) -> str:
        """
        Provide context aware response based on the memory.
        Retrieve relevant information from the memory for the given query.
        """
        try:
            log_debug(f"Searching memory: {query}")

            loop = asyncio.get_event_loop()

            async def _search():
                await self._add_queue.join()
                result = await cognee.search(query_text=query, top_k=100)
                return result

            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, _search())
                    results = future.result()
            else:
                results = loop.run_until_complete(_search())

            serializable_results: List[Any] = []
            for item in results:
                if isinstance(item, dict):
                    serializable_item = {}
                    for key, value in item.items():
                        if hasattr(value, '__str__'):
                            serializable_item[key] = str(value)
                        else:
                            serializable_item[key] = value
                    serializable_results.append(serializable_item)
                else:
                    serializable_results.append(str(item))

            return json.dumps(serializable_results)

        except Exception as e:
            log_error(f"Error searching memory: {e}")
            return f"Error searching memory: {e}"
