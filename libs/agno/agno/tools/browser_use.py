import json
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    from browser_use_sdk.v4 import AsyncBrowserUse, BrowserUse, BrowserUseError
except ImportError:
    raise ImportError("`browser-use-sdk` not installed. Please install using `pip install browser-use-sdk`")


class BrowserUseTools(Toolkit):
    """Run browser tasks with the Browser Use Cloud agent (API v4).

    The agent describes a task in plain language. Browser Use opens a cloud browser,
    navigates, clicks, fills forms and extracts data, then returns its final answer.

    Args:
        api_key (Optional[str]): Browser Use API key. Defaults to the BROWSER_USE_API_KEY environment variable.
        model (Optional[str]): Browser Use agent model. Defaults to the API default.
        timeout (int): Seconds to wait for a run. A run that does not finish in time is cancelled. Default is 900.
        enable_run_browser_task (bool): Enable the run_browser_task tool. Default is True.
        all (bool): Enable all tools. Default is False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 900,
        enable_run_browser_task: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.api_key: Optional[str] = api_key or getenv("BROWSER_USE_API_KEY")
        if not self.api_key:
            log_error("BROWSER_USE_API_KEY not set. Please set the BROWSER_USE_API_KEY environment variable.")
        self.model = model

        tools: List[Any] = []
        async_tools: List[tuple] = []
        if all or enable_run_browser_task:
            tools.append(self.run_browser_task)
            async_tools.append((self.arun_browser_task, "run_browser_task"))

        super().__init__(name="browser_use_tools", tools=tools, async_tools=async_tools, timeout=timeout, **kwargs)

    def run_browser_task(self, task: str, session_id: Optional[str] = None) -> str:
        """Use this function to complete a task on the web with a browser agent.
        The agent can navigate websites, click, fill forms, log in and extract data.

        Args:
            task (str): What to do in the browser, in plain language. Name the website and the exact information or action you need.
            session_id (Optional[str]): session_id from a previous result, to continue in the same browser and conversation.

        Returns:
            str: JSON with the agent's result and the session_id, or an error.
        """
        if not self.api_key:
            return _error("BROWSER_USE_API_KEY not set")
        log_debug(f"Running Browser Use task: {task}")
        with BrowserUse(api_key=self.api_key) as client:
            try:
                run = client.runs.create(task, model=self.model, session_id=session_id or None)
                summary = client.runs.wait_for_completion(run.id, timeout=self.timeout)
            except BrowserUseError as e:
                return _error(f"Browser Use API error {e.status_code}: {e.message}")
            except TimeoutError:
                try:
                    client.runs.cancel(run.id)
                except BrowserUseError as e:
                    log_error(f"Failed to cancel Browser Use run {run.id}: {e}")
                return _timeout_error(run, self.timeout)
        return _summary_output(summary)

    async def arun_browser_task(self, task: str, session_id: Optional[str] = None) -> str:
        """Use this function to complete a task on the web with a browser agent.
        The agent can navigate websites, click, fill forms, log in and extract data.

        Args:
            task (str): What to do in the browser, in plain language. Name the website and the exact information or action you need.
            session_id (Optional[str]): session_id from a previous result, to continue in the same browser and conversation.

        Returns:
            str: JSON with the agent's result and the session_id, or an error.
        """
        if not self.api_key:
            return _error("BROWSER_USE_API_KEY not set")
        log_debug(f"Running Browser Use task: {task}")
        async with AsyncBrowserUse(api_key=self.api_key) as client:
            try:
                run = await client.runs.create(task, model=self.model, session_id=session_id or None)
                summary = await client.runs.wait_for_completion(run.id, timeout=self.timeout)
            except BrowserUseError as e:
                return _error(f"Browser Use API error {e.status_code}: {e.message}")
            except TimeoutError:
                try:
                    await client.runs.cancel(run.id)
                except BrowserUseError as e:
                    log_error(f"Failed to cancel Browser Use run {run.id}: {e}")
                return _timeout_error(run, self.timeout)
        return _summary_output(summary)


def _summary_output(summary: Any) -> str:
    status = summary.status.value
    if status != "completed":
        return _error(
            f"Browser Use run {status}: {summary.error or 'no error message'}",
            run_id=str(summary.id),
            session_id=str(summary.session_id),
        )
    return json.dumps({"result": summary.result, "session_id": str(summary.session_id), "run_id": str(summary.id)})


def _timeout_error(run: Any, timeout: Any) -> str:
    return _error(
        f"Browser Use run did not finish within {timeout}s and was cancelled. Try a smaller task.",
        run_id=str(run.id),
        session_id=str(run.session_id),
    )


def _error(message: str, **details: str) -> str:
    log_error(message)
    return json.dumps({"error": message, **details})
