from typing import Dict, List, Optional, Set
import os
import inspect
import importlib
from pathlib import Path
from agno.tools.function import Function


def get_agents_tools(
	tools_dir: str = "src/tools",
	recursive: bool = False,
	exclude_patterns: Optional[Set[str]] = None,
	include_patterns: Optional[Set[str]] = None,
) -> Dict[str, List[Function]]:
	"""
	Dynamically retrieves tool functions organized by agent name from the tools directory.
	Each <agent_name>.py file in the tools directory represents an agent's toolset.

	Args:
	    tools_dir (str): Path to the tools directory. Defaults to "src/tools".
	    recursive (bool): If True, recursively search subdirectories for tool modules.
	    exclude_patterns (Optional[Set[str]]): Set of glob patterns to exclude from search.
	    include_patterns (Optional[Set[str]]): Set of glob patterns to include in search.

	Returns:
	    Dict[str, List[Function]]: Dictionary mapping agent names to their respective tools list.
	    Example: {
	        'agent_name': [tool1, tool2],
	        ...
	    }

	Raises:
	    FileNotFoundError: If the tools directory doesn't exist.
	    ImportError: If there's an error importing a module.
	    ValueError: If the module structure is invalid.

	Example:
	    >>> tools = get_agents_tools()
	    >>> tools = get_agents_tools(recursive=True, exclude_patterns={"*_test.py"})
	"""
	tools_dir_path = Path(tools_dir)
	if not tools_dir_path.exists():
		raise FileNotFoundError(f"Tools directory not found: {tools_dir}")

	agent_tools: Dict[str, List[Function]] = {}
	exclude_patterns = exclude_patterns or set()
	include_patterns = include_patterns or set()

	def should_process_file(filename: str) -> bool:
		"""Check if a file should be processed based on patterns."""
		if not filename.endswith(".py") or filename == "__init__.py":
			return False
		
		# Check include patterns first
		if include_patterns and not any(filename.endswith(p.replace("*", "")) for p in include_patterns):
			return False
			
		# Then check exclude patterns
		if any(filename.endswith(p.replace("*", "")) for p in exclude_patterns):
			return False
			
		return True

	def process_module(module_path: Path, agent_name: str) -> None:
		"""Process a single module and extract its tools."""
		try:
			module_spec = importlib.util.spec_from_file_location(
				f"src.tools.{agent_name}",
				str(module_path)
			)
			
			if not module_spec or not module_spec.loader:
				return

			module = importlib.util.module_from_spec(module_spec)
			module_spec.loader.exec_module(module)

			tools = []
			for name, obj in inspect.getmembers(module):
				if isinstance(obj, Function):
					tools.append(obj)

			if tools:
				agent_tools[agent_name] = tools

		except ImportError as e:
			raise ImportError(f"Failed to import module {agent_name}: {str(e)}")
		except Exception as e:
			raise ValueError(f"Error processing module {agent_name}: {str(e)}")

	# Process files in the tools directory
	if recursive:
		for module_path in tools_dir_path.rglob("*.py"):
			if should_process_file(module_path.name):
				# Get agent name from relative path
				agent_name = module_path.stem
				process_module(module_path, agent_name)
	else:
		for filename in os.listdir(tools_dir):
			if should_process_file(filename):
				agent_name = filename[:-3]  # Remove .py extension
				module_path = tools_dir_path / filename
				process_module(module_path, agent_name)

	return agent_tools