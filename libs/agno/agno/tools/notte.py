import asyncio
import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    from notte_sdk import NotteClient
except ImportError:
    raise ImportError("`notte-sdk` not installed. Please install using `pip install notte-sdk`")


class NotteTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        server_url: Optional[str] = None,
        headless: bool = True,
        solve_captchas: bool = False,
        proxies: bool = False,
        browser_type: str = "chromium",
        timeout_minutes: Optional[int] = None,
        perception_type: str = "fast",
        reasoning_model: Optional[str] = None,
        max_agent_steps: int = 15,
        enable_navigate_to: bool = True,
        enable_screenshot: bool = True,
        enable_get_page_content: bool = True,
        enable_observe: bool = True,
        enable_click: bool = True,
        enable_fill: bool = True,
        enable_scrape: bool = True,
        enable_run_agent: bool = True,
        enable_close_session: bool = True,
        all: bool = False,
        max_content_length: Optional[int] = 100000,
        **kwargs,
    ):
        """Initialize NotteTools.

        Args:
            api_key (str, optional): Notte API key. If not provided, reads NOTTE_API_KEY env var.
            server_url (str, optional): Custom Notte API endpoint. Only set this for self-hosted
                deployments or non-default regions. Defaults to https://api.notte.cc.
            headless (bool): Run the remote browser headless. Defaults to True.
            solve_captchas (bool): Automatically solve captchas during the session. Defaults to False.
            proxies (bool): Route the session through Notte's proxy pool. Defaults to False.
            browser_type (str): One of "chromium", "chrome", "firefox". Defaults to "chromium".
            timeout_minutes (int, optional): Hard timeout for the remote session in minutes.
            perception_type (str): "fast" or "deep". Controls how aggressively Notte parses the DOM
                into an action space. Defaults to "fast".
            reasoning_model (str, optional): LLM identifier passed through to the Notte agent
                (e.g. "gemini/gemini-2.5-flash"). Used by the run_agent tool only.
            max_agent_steps (int): Default step cap for run_agent. Defaults to 15.
            enable_navigate_to (bool): Enable the navigate_to tool. Defaults to True.
            enable_screenshot (bool): Enable the screenshot tool. Defaults to True.
            enable_get_page_content (bool): Enable the get_page_content tool. Defaults to True.
            enable_observe (bool): Enable the observe tool. Defaults to True.
            enable_click (bool): Enable the click tool. Defaults to True.
            enable_fill (bool): Enable the fill tool. Defaults to True.
            enable_scrape (bool): Enable the scrape tool. Defaults to True.
            enable_run_agent (bool): Enable the run_agent tool. Defaults to True.
            enable_close_session (bool): Enable the close_session tool. Defaults to True.
            all (bool): Enable all tools regardless of individual flags. Defaults to False.
            max_content_length (int, optional): Truncate page content above this many characters.
                Defaults to 100000. Set to None for no limit.
        """
        self.api_key = api_key or getenv("NOTTE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "NOTTE_API_KEY is required. Please set the NOTTE_API_KEY environment variable."
            )

        self.server_url = server_url or getenv("NOTTE_API_URL")
        self.max_content_length = max_content_length
        self.reasoning_model = reasoning_model
        self.max_agent_steps = max_agent_steps

        self._session_kwargs: Dict[str, Any] = {
            "headless": headless,
            "solve_captchas": solve_captchas,
            "proxies": proxies,
            "browser_type": browser_type,
            "perception_type": perception_type,
        }
        if timeout_minutes is not None:
            self._session_kwargs["timeout_minutes"] = timeout_minutes

        client_kwargs: Dict[str, Any] = {"api_key": self.api_key}
        if self.server_url:
            client_kwargs["server_url"] = self.server_url
            log_debug(f"Using custom Notte API endpoint: {self.server_url}")
        self.client = NotteClient(**client_kwargs)

        self._session: Any = None

        # Build tools lists
        # sync tools: used by agent.run() and agent.print_response()
        # async tools: used by agent.arun() and agent.aprint_response()
        tools: List[Any] = []
        async_tools: List[tuple] = []

        if all or enable_navigate_to:
            tools.append(self.navigate_to)
            async_tools.append((self.anavigate_to, "navigate_to"))
        if all or enable_screenshot:
            tools.append(self.screenshot)
            async_tools.append((self.ascreenshot, "screenshot"))
        if all or enable_get_page_content:
            tools.append(self.get_page_content)
            async_tools.append((self.aget_page_content, "get_page_content"))
        if all or enable_observe:
            tools.append(self.observe)
            async_tools.append((self.aobserve, "observe"))
        if all or enable_click:
            tools.append(self.click)
            async_tools.append((self.aclick, "click"))
        if all or enable_fill:
            tools.append(self.fill)
            async_tools.append((self.afill, "fill"))
        if all or enable_scrape:
            tools.append(self.scrape)
            async_tools.append((self.ascrape, "scrape"))
        if all or enable_run_agent:
            tools.append(self.run_agent)
            async_tools.append((self.arun_agent, "run_agent"))
        if all or enable_close_session:
            tools.append(self.close_session)
            async_tools.append((self.aclose_session, "close_session"))

        super().__init__(name="notte_tools", tools=tools, async_tools=async_tools, **kwargs)

    # -- session management --

    def _ensure_session(self) -> None:
        """Ensures a remote Notte session exists, creating one if needed."""
        if self._session is None:
            try:
                self._session = self.client.Session(**self._session_kwargs)
                self._session.start()
                log_debug(f"Started Notte session with ID: {self._session.session_id}")
            except Exception:
                logger.exception("Failed to start Notte session")
                raise

    def _truncate(self, content: str) -> str:
        """Truncate content if it exceeds max_content_length."""
        if self.max_content_length is None or len(content) <= self.max_content_length:
            return content
        truncated = content[: self.max_content_length]
        return (
            f"{truncated}\n\n[Content truncated. Original length: {len(content)} characters. "
            f"Showing first {self.max_content_length} characters.]"
        )

    @staticmethod
    def _normalise_id(element_id: str) -> str:
        """Strip an optional leading '@' from a Notte element ID."""
        if not element_id:
            return element_id
        return element_id.lstrip("@").strip()

    # -- sync tools --

    def navigate_to(self, url: str) -> str:
        """Navigates the remote browser to a URL.

        Args:
            url (str): The URL to navigate to.

        Returns:
            JSON string with navigation status.
        """
        try:
            self._ensure_session()
            self._session.execute(type="goto", url=url)
            return json.dumps({"status": "complete", "url": url})
        except Exception as e:
            logger.exception("navigate_to failed")
            return json.dumps({"status": "error", "url": url, "message": str(e)})

    def screenshot(self, path: str, full_page: bool = True) -> str:
        """Captures a screenshot of the current page and writes it to disk.

        Args:
            path (str): Where to save the screenshot.
            full_page (bool): Hint for full-page capture. Notte returns the rendered viewport;
                full-page support depends on the underlying perception mode.

        Returns:
            JSON string confirming the screenshot was saved.
        """
        try:
            self._ensure_session()
            obs = self._session.observe()
            data = obs.screenshot.bytes()
            with open(path, "wb") as f:
                f.write(data)
            return json.dumps({"status": "success", "path": path})
        except Exception as e:
            logger.exception("screenshot failed")
            return json.dumps({"status": "error", "path": path, "message": str(e)})

    def get_page_content(self) -> str:
        """Returns the current page content as clean markdown.

        Returns:
            Page content as markdown, truncated to max_content_length characters.
        """
        try:
            self._ensure_session()
            content = self._session.scrape(only_main_content=True)
            return self._truncate(content if isinstance(content, str) else str(content))
        except Exception as e:
            logger.exception("get_page_content failed")
            return json.dumps({"status": "error", "message": str(e)})

    def observe(self, instructions: Optional[str] = None) -> str:
        """Observes the current page and returns the available action space.

        Each interactive element is given a stable ID (e.g. B1 for buttons, I1 for inputs,
        L1 for links) that can be passed to click, fill, or other action tools.

        Args:
            instructions (str, optional): Natural-language hint to focus the observation.

        Returns:
            JSON string with url, title, and the action space listing.
        """
        try:
            self._ensure_session()
            kwargs: Dict[str, Any] = {}
            if instructions:
                kwargs["instructions"] = instructions
            obs = self._session.observe(**kwargs)
            description = obs.space.description if obs.space else ""
            metadata = obs.metadata
            payload = {
                "url": getattr(metadata, "url", None),
                "title": getattr(metadata, "title", None),
                "action_space": self._truncate(description),
            }
            return json.dumps(payload)
        except Exception as e:
            logger.exception("observe failed")
            return json.dumps({"status": "error", "message": str(e)})

    def click(self, element_id: str) -> str:
        """Clicks an interactive element by its Notte ID.

        Args:
            element_id (str): The element ID returned by observe (e.g. "B1", "L3").

        Returns:
            JSON string with the click status.
        """
        try:
            self._ensure_session()
            normalised = self._normalise_id(element_id)
            result = self._session.execute(type="click", id=normalised)
            return json.dumps({
                "status": "success" if getattr(result, "success", True) else "failed",
                "element_id": normalised,
                "message": getattr(result, "message", ""),
            })
        except Exception as e:
            logger.exception("click failed")
            return json.dumps({"status": "error", "element_id": element_id, "message": str(e)})

    def fill(self, element_id: str, value: str) -> str:
        """Fills an input element by its Notte ID with the provided value.

        Args:
            element_id (str): The input ID returned by observe (e.g. "I1").
            value (str): The text to type into the input.

        Returns:
            JSON string with the fill status.
        """
        try:
            self._ensure_session()
            normalised = self._normalise_id(element_id)
            result = self._session.execute(type="fill", id=normalised, value=value)
            return json.dumps({
                "status": "success" if getattr(result, "success", True) else "failed",
                "element_id": normalised,
                "message": getattr(result, "message", ""),
            })
        except Exception as e:
            logger.exception("fill failed")
            return json.dumps({"status": "error", "element_id": element_id, "message": str(e)})

    def scrape(self, instructions: Optional[str] = None, only_main_content: bool = True) -> str:
        """Scrapes the current page, optionally guided by natural-language instructions.

        Args:
            instructions (str, optional): When set, Notte returns structured data extracted
                according to the instructions. When omitted, returns the page as markdown.
            only_main_content (bool): Strip headers, footers, and navigation when True. Defaults to True.

        Returns:
            Markdown string when no instructions are given, else a JSON string of the extracted data.
        """
        try:
            self._ensure_session()
            if instructions:
                result = self._session.scrape(instructions=instructions)
                data = getattr(result, "data", result)
                if hasattr(data, "model_dump_json"):
                    serialised = data.model_dump_json()
                else:
                    serialised = json.dumps(data, default=str)
                return self._truncate(serialised)
            content = self._session.scrape(only_main_content=only_main_content)
            return self._truncate(content if isinstance(content, str) else str(content))
        except Exception as e:
            logger.exception("scrape failed")
            return json.dumps({"status": "error", "message": str(e)})

    def run_agent(
        self,
        task: str,
        url: Optional[str] = None,
        max_steps: Optional[int] = None,
    ) -> str:
        """Hands a multi-step task to a Notte browser agent and returns its final answer.

        Use this for complex flows that would otherwise require many sequential observe and
        act calls. The agent runs inside the same session.

        Args:
            task (str): Natural-language description of the task.
            url (str, optional): Starting URL. If omitted, uses the current page.
            max_steps (int, optional): Override the toolkit-level step cap.

        Returns:
            JSON string with the agent's final answer and metadata.
        """
        try:
            self._ensure_session()
            agent_kwargs: Dict[str, Any] = {
                "session": self._session,
                "max_steps": max_steps or self.max_agent_steps,
            }
            if self.reasoning_model:
                agent_kwargs["reasoning_model"] = self.reasoning_model
            agent = self.client.Agent(**agent_kwargs)
            result = agent.run(task=task, url=url)
            return json.dumps({
                "status": "complete",
                "answer": getattr(result, "answer", ""),
                "agent_id": getattr(agent, "agent_id", ""),
            })
        except Exception as e:
            logger.exception("run_agent failed")
            return json.dumps({"status": "error", "task": task, "message": str(e)})

    def close_session(self) -> str:
        """Stops the current Notte session and releases remote browser resources.

        Returns:
            JSON string with the closure status.
        """
        try:
            if self._session is not None:
                self._session.stop()
                self._session = None
            return json.dumps({"status": "closed", "message": "Notte session stopped."})
        except Exception as e:
            return json.dumps({"status": "warning", "message": f"Cleanup completed with warning: {str(e)}"})

    # -- async tools --
    # Notte's SDK exposes synchronous methods. The async siblings below offload the sync work
    # to a thread so the event loop is never blocked in async agent flows.

    async def anavigate_to(self, url: str) -> str:
        """Navigates the remote browser to a URL asynchronously."""
        return await asyncio.to_thread(self.navigate_to, url)

    async def ascreenshot(self, path: str, full_page: bool = True) -> str:
        """Captures a screenshot of the current page asynchronously."""
        return await asyncio.to_thread(self.screenshot, path, full_page)

    async def aget_page_content(self) -> str:
        """Returns the current page content as clean markdown asynchronously."""
        return await asyncio.to_thread(self.get_page_content)

    async def aobserve(self, instructions: Optional[str] = None) -> str:
        """Observes the current page asynchronously."""
        return await asyncio.to_thread(self.observe, instructions)

    async def aclick(self, element_id: str) -> str:
        """Clicks an interactive element by its Notte ID asynchronously."""
        return await asyncio.to_thread(self.click, element_id)

    async def afill(self, element_id: str, value: str) -> str:
        """Fills an input element by its Notte ID asynchronously."""
        return await asyncio.to_thread(self.fill, element_id, value)

    async def ascrape(self, instructions: Optional[str] = None, only_main_content: bool = True) -> str:
        """Scrapes the current page asynchronously."""
        return await asyncio.to_thread(self.scrape, instructions, only_main_content)

    async def arun_agent(
        self,
        task: str,
        url: Optional[str] = None,
        max_steps: Optional[int] = None,
    ) -> str:
        """Hands a multi-step task to a Notte browser agent asynchronously."""
        return await asyncio.to_thread(self.run_agent, task, url, max_steps)

    async def aclose_session(self) -> str:
        """Stops the current Notte session asynchronously."""
        return await asyncio.to_thread(self.close_session)
