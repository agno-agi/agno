# agno/tools/base.py
from typing import Callable
 
# Dummy decorator to mark tool methods
def tool(func: Callable) -> Callable:
    return func
 
# Dummy base class for all tools
class BaseTool:
    def __init__(self):
        pass
 