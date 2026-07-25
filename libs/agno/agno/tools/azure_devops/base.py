from os import getenv
from typing import Any, Dict, Optional

from agno.tools import Toolkit

try:
    from azure.devops.connection import Connection
    from msrest.authentication import BasicAuthentication
except ImportError:
    raise ImportError("`azure-devops` not installed. Please install using `pip install azure-devops`")


class AzureDevOpsBaseTools(Toolkit):
    """Shared base for Azure DevOps toolkits.

    Holds the organization URL, personal access token and default project, builds the
    Azure DevOps SDK connection lazily and exposes typed clients plus project resolution.
    """

    def __init__(
        self,
        organization_url: Optional[str] = None,
        personal_access_token: Optional[str] = None,
        project: Optional[str] = None,
        **kwargs: Any,
    ):
        self.organization_url = organization_url or getenv("AZURE_DEVOPS_ORG_URL")
        self.personal_access_token = personal_access_token or getenv("AZURE_DEVOPS_PAT")
        self.project = project or getenv("AZURE_DEVOPS_PROJECT")

        if not self.organization_url:
            raise ValueError(
                "Azure DevOps organization URL not provided. "
                "Pass organization_url or set the AZURE_DEVOPS_ORG_URL environment variable."
            )
        if not self.personal_access_token:
            raise ValueError(
                "Azure DevOps personal access token not provided. "
                "Pass personal_access_token or set the AZURE_DEVOPS_PAT environment variable."
            )

        self._connection: Optional[Connection] = None
        self._clients: Dict[str, Any] = {}

        super().__init__(**kwargs)

    def _get_connection(self) -> Connection:
        if self._connection is None:
            credentials = BasicAuthentication("", self.personal_access_token or "")
            self._connection = Connection(base_url=self.organization_url, creds=credentials)
        return self._connection

    def _get_client(self, key: str) -> Any:
        if key not in self._clients:
            clients = self._get_connection().clients
            factories = {
                "git": clients.get_git_client,
                "wiki": clients.get_wiki_client,
                "work": clients.get_work_client,
                "wit": clients.get_work_item_tracking_client,
                "core": clients.get_core_client,
            }
            client = factories[key]()
            if client is None:
                raise RuntimeError(f"Failed to get Azure DevOps {key} client.")
            self._clients[key] = client
        return self._clients[key]

    def _get_git_client(self) -> Any:
        return self._get_client("git")

    def _get_wiki_client(self) -> Any:
        return self._get_client("wiki")

    def _get_work_client(self) -> Any:
        return self._get_client("work")

    def _get_wit_client(self) -> Any:
        return self._get_client("wit")

    def _get_core_client(self) -> Any:
        return self._get_client("core")

    def _resolve_project(self, project: Optional[str] = None) -> str:
        resolved = project or self.project
        if not resolved:
            raise ValueError(
                "Azure DevOps project not provided. Pass project or set the AZURE_DEVOPS_PROJECT environment variable."
            )
        return resolved
