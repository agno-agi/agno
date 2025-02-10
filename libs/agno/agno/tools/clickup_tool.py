import json
import os
import re
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    import requests
except ImportError:
    raise ImportError("`requests` not installed. Please install using `pip install requests`")


class ClickUpTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        master_space_id: Optional[str] = None,
        list_tasks: bool = True,
        create_task: bool = True,
        get_task: bool = True,
        update_task: bool = True,
        delete_task: bool = True,
        list_spaces: bool = True,
        list_lists: bool = True,
    ):
        super().__init__(name="clickup")

        self.api_key = api_key or os.getenv("CLICKUP_API_KEY")
        self.master_space_id = master_space_id or os.getenv("MASTER_SPACE_ID")
        self.base_url = "https://api.clickup.com/api/v2"
        self.headers = {"Authorization": self.api_key}

        if not self.api_key:
            raise ValueError("CLICKUP_API_KEY not set. Please set the CLICKUP_API_KEY environment variable.")
        if not self.master_space_id:
            raise ValueError("MASTER_SPACE_ID not set. Please set the MASTER_SPACE_ID environment variable.")

        if list_tasks:
            self.register(self.list_tasks)
        if create_task:
            self.register(self.create_task)
        if get_task:
            self.register(self.get_task)
        if update_task:
            self.register(self.update_task)
        if delete_task:
            self.register(self.delete_task)
        if list_spaces:
            self.register(self.list_spaces)
        if list_lists:
            self.register(self.list_lists)

    def _make_request(
        self, method: str, endpoint: str, params: Optional[Dict] = None, data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make a request to the ClickUp API."""
        url = f"{self.base_url}/{endpoint}"
        try:
            response = requests.request(method=method, url=url, headers=self.headers, params=params, json=data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error making request to {url}: {e}")
            return {"error": str(e)}

    def _find_by_name(self, items: List[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
        """Find an item in a list by name using exact match or regex pattern.

        Args:
            items: List of items to search through
            name: Name to search for

        Returns:
            Matching item or None if not found
        """
        if not name:
            return items[0] if items else None

        pattern = re.compile(name, re.IGNORECASE)
        for item in items:
            # Try exact match first (case-insensitive)
            if item["name"].lower() == name.lower():
                return item
            # Then try regex pattern match
            if pattern.search(item["name"]):
                return item
        return None

    def _get_space(self, space_name: str) -> Dict[str, Any]:
        """Get space information by name."""
        spaces = self._make_request("GET", f"team/{self.master_space_id}/space")
        if "error" in spaces:
            return spaces

        spaces_list = spaces.get("spaces", [])
        if not spaces_list:
            return {"error": "No spaces found"}

        space = self._find_by_name(spaces_list, space_name)
        if not space:
            return {"error": f"Space '{space_name}' not found"}
        return space

    def _get_list(self, space_id: str, list_name: str) -> Dict[str, Any]:
        """Get list information by name."""
        lists = self._make_request("GET", f"space/{space_id}/list")
        if "error" in lists:
            return lists

        lists_data = lists.get("lists", [])
        if not lists_data:
            return {"error": "No lists found in space"}

        list_item = self._find_by_name(lists_data, list_name)
        if not list_item:
            return {"error": f"List '{list_name}' not found"}
        return list_item

    def _get_tasks(self, list_id: str) -> List[Dict[str, Any]]:
        """Get tasks in a list, optionally filtered by name."""
        tasks = self._make_request("GET", f"list/{list_id}/task")
        if "error" in tasks:
            return []

        tasks_data = tasks.get("tasks", [])
        return tasks_data

    def list_tasks(self, space_name: str) -> str:
        """List all tasks in a space.

        Args:
            space_name (str): Name of the space to list tasks from

        Returns:
            str: JSON string containing tasks
        """
        # Get space
        space = self._get_space(space_name)
        if "error" in space:
            return json.dumps(space, indent=2)

        # Get lists
        lists = self._make_request("GET", f"space/{space['id']}/list")
        lists_data = lists.get("lists", [])
        if not lists_data:
            return json.dumps({"error": f"No lists found in space '{space_name}'"}, indent=2)

        # Get tasks from all lists
        all_tasks = []
        for list_info in lists_data:
            tasks = self._get_tasks(list_info["id"])
            for task in tasks:
                task["list_name"] = list_info["name"]  # Add list name for context
            all_tasks.extend(tasks)

        return json.dumps({"tasks": all_tasks}, indent=2)

    def create_task(self, space_name: str, task_name: str, task_description: str) -> str:
        """Create a new task in a space.

        Args:
            space_name (str): Name of the space to create task in
            task_name (str): Name of the task
            task_description (str): Description of the task

        Returns:
            str: JSON string containing created task details
        """
        # Get space
        space = self._get_space(space_name)
        if "error" in space:
            return json.dumps(space, indent=2)

        # Get first list in space
        response = self._make_request("GET", f"space/{space['id']}/list")
        logger.debug(f"Lists: {response}")
        lists_data = response.get("lists", [])
        if not lists_data:
            return json.dumps({"error": f"No lists found in space '{space_name}'"}, indent=2)

        list_info = lists_data[0]  # Use first list

        # Create task
        data = {"name": task_name, "description": task_description}

        task = self._make_request("POST", f"list/{list_info['id']}/task", data=data)
        return json.dumps(task, indent=2)

    def list_spaces(self) -> str:
        """List all spaces in the workspace.

        Returns:
            str: JSON string containing list of spaces
        """
        spaces = self._make_request("GET", f"team/{self.master_space_id}/space")
        return json.dumps(spaces, indent=2)

    def list_lists(self, space_name: str) -> str:
        """List all lists in a space.

        Args:
            space_name (str): Name of the space to list lists from

        Returns:
            str: JSON string containing list of lists
        """
        # Get space
        space = self._get_space(space_name)
        if "error" in space:
            return json.dumps(space, indent=2)

        # Get lists
        lists = self._make_request("GET", f"space/{space['id']}/list")
        return json.dumps(lists, indent=2)

    def get_task(self, task_id: str) -> str:
        """Get details of a specific task.

        Args:
            task_id (str): The ID of the task

        Returns:
            str: JSON string containing task details
        """
        task = self._make_request("GET", f"task/{task_id}")
        return json.dumps(task, indent=2)

    def update_task(self, task_id: str, **kwargs) -> str:
        """Update a specific task.

        Args:
            task_id (str): The ID of the task
            **kwargs: Task fields to update (name, description, status, priority, etc.)

        Returns:
            str: JSON string containing updated task details
        """
        task = self._make_request("PUT", f"task/{task_id}", data=kwargs)
        return json.dumps(task, indent=2)

    def delete_task(self, task_id: str) -> str:
        """Delete a specific task.

        Args:
            task_id (str): The ID of the task

        Returns:
            str: JSON string containing deletion status
        """
        result = self._make_request("DELETE", f"task/{task_id}")
        if "error" not in result:
            result = {"success": True, "message": f"Task {task_id} deleted successfully"}
        return json.dumps(result, indent=2)
