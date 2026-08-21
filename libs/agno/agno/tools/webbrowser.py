import json
import webbrowser
from typing import Callable, List

from agno.tools import Toolkit


class WebBrowserTools(Toolkit):
    """Toolkit for opening URLs in the system web browser.

    Args:
        open_page: Enable open_page tool. Defaults to False (opens external browser).
        all: Enable all tools. Defaults to False.
    """

    def __init__(self, open_page: bool = False, all: bool = False, **kwargs):
        tools: List[Callable] = []
        if all or open_page:
            tools.append(self.open_page)

        super().__init__(name="webbrowser_tools", tools=tools, **kwargs)

    def open_page(self, url: str, new_window: bool = False) -> str:
        """Open a URL in the system web browser.

        Args:
            url: URL to open.
            new_window: Open in a new window instead of a new tab. Defaults to False.

        Returns:
            JSON with status.
        """
        try:
            if new_window:
                webbrowser.open_new(url)
            else:
                webbrowser.open_new_tab(url)
            return json.dumps({"status": "success", "url": url, "new_window": new_window})
        except Exception as e:
            return json.dumps({"error": f"Failed to open browser: {e}"})
