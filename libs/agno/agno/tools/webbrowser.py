import webbrowser
from typing import Any, List

from agno.tools import Toolkit


class WebBrowserTools(Toolkit):
    """Tools for opening a page on the web browser"""

    def __init__(self):
        tools: List[Any] = []
        tools.append(self.open_page)

        super().__init__(name="webbrowser_tools", tools=tools)

    def open_page(self, url: str, new_window: bool = False):
        """Open a URL in a browser window
        Args:
            url (str): URL to open
            new_window (bool): If True, open in a new window, otherwise open in a new tab. Default is False.
        Returns:
            None
        """
        if new_window:
            webbrowser.open_new(url)
        else:
            webbrowser.open_new_tab(url)
