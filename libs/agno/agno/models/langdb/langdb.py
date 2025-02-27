from dataclasses import dataclass
from os import getenv
from typing import Optional, Dict, Any
import inspect
from agno.utils.log import logger
from agno.models.openai.like import OpenAILike


@dataclass
class LangDB(OpenAILike):
    """
    A class for using models hosted on LangDB.

    Attributes:
        id (str): The model id. Defaults to "gpt-4o".
        name (str): The model name. Defaults to "LangDB".
        provider (str): The provider name. Defaults to "LangDB: " + id.
        api_key (Optional[str]): The API key. Defaults to getenv("LANGDB_API_KEY").
        project_id (Optional[str]): The project id. Defaults to None.
    """

    id: str = "gpt-4o"
    name: str = "LangDB"
    provider: str = "LangDB: " + id

    api_key: Optional[str] = getenv("LANGDB_API_KEY")
    project_id: Optional[str] = getenv("LANGDB_PROJECT_ID")
    if not project_id:
        logger.warning("LANGDB_PROJECT_ID not set in the environment")
    base_url: str = f"https://api.us-east-1.langdb.ai/{project_id}/v1"
    label: Optional[str] = None
    default_headers: Optional[dict] = None

    def _get_client_params(self) -> Dict[str, Any]:
        # Initialize headers with label if present
        if self.label and not self.default_headers:
            self.default_headers = {
                "x-label": self.label,
            }
        client_params = super()._get_client_params()

        # Get the current workflow's run_id and session_id if we're in a workflow context
        # This is done by walking up the call stack to find the workflow instance
        frame = inspect.currentframe()
        workflow_run_id = None
        workflow_session_id = None

        while frame:
            if 'self' in frame.f_locals:
                instance = frame.f_locals['self']
                if hasattr(instance, 'workflow'):
                    # If it's an Agent with a workflow
                    workflow = instance.workflow
                    if workflow.run_id:
                        workflow_run_id = workflow.run_id
                    if workflow.session_id:
                        workflow_session_id = workflow.session_id
                    break
                elif hasattr(instance, 'run_id'):
                    # If it's a workflow instance
                    if instance.run_id:
                        workflow_run_id = instance.run_id
                    if instance.session_id:
                        workflow_session_id = instance.session_id
                    break
            frame = frame.f_back

        # Set the headers if we found a workflow run_id or session_id
        if workflow_run_id or workflow_session_id:
            if 'default_headers' not in client_params:
                client_params['default_headers'] = {}
            if workflow_run_id:
                client_params['default_headers']['x-run-id'] = workflow_run_id
            if workflow_session_id:
                client_params['default_headers']['x-thread-id'] = workflow_session_id

        return client_params
