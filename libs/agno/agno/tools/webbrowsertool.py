import webbrowser

from agno.tools import Toolkit
from agno.utils.log import logger

class WebBrowserTools(Toolkit):
    """Tools for opening a page on the web browser"""
    def __init__(self):
        super().__init__(name="webbrowser_tools")
        self.register(self.open_page)
    def open_page(self,url:str):
        """Open a URL in a browser window
        Args:
            url: URL to open
        Returns:
            None
        """
        webbrowser.open_new_tab(url)