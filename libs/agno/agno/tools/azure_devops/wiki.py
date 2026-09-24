import asyncio
import json
from typing import Any, Dict, List, Optional

from agno.tools.azure_devops.base import AzureDevOpsBaseTools
from agno.utils.log import log_debug, log_error

try:
    from azure.devops.v7_1.wiki.models import WikiPagesBatchRequest
except ImportError:
    raise ImportError("`azure-devops` not installed. Please install using `pip install azure-devops`")


def _format_wiki_page(page: Any) -> Dict[str, Any]:
    return {
        "id": page.id,
        "content": page.content,
        "is_parent_page": page.is_parent_page,
        "order": page.order,
        "path": page.path,
        "remote_url": page.remote_url,
        "sub_pages": page.sub_pages,
    }


class AzureDevOpsWikiTools(AzureDevOpsBaseTools):
    """Toolkit for Azure DevOps project wikis."""

    def __init__(
        self,
        organization_url: Optional[str] = None,
        personal_access_token: Optional[str] = None,
        project: Optional[str] = None,
        enable_get_wiki_list: bool = True,
        enable_get_wiki_pages: bool = True,
        enable_list_wiki_pages: bool = True,
        enable_search_in_wiki_pages: bool = True,
        **kwargs: Any,
    ):
        tools: List[Any] = []
        async_tools: List[tuple[Any, str]] = []

        if enable_get_wiki_list:
            tools.append(self.get_wiki_list)
            async_tools.append((self.aget_wiki_list, "get_wiki_list"))
        if enable_get_wiki_pages:
            tools.append(self.get_wiki_pages)
            async_tools.append((self.aget_wiki_pages, "get_wiki_pages"))
        if enable_list_wiki_pages:
            tools.append(self.list_wiki_pages)
            async_tools.append((self.alist_wiki_pages, "list_wiki_pages"))
        if enable_search_in_wiki_pages:
            tools.append(self.search_in_wiki_pages)
            async_tools.append((self.asearch_in_wiki_pages, "search_in_wiki_pages"))

        super().__init__(
            organization_url=organization_url,
            personal_access_token=personal_access_token,
            project=project,
            name="azure_devops_wiki",
            tools=tools,
            async_tools=async_tools,
            **kwargs,
        )

    def get_wiki_list(self, project: Optional[str] = None) -> str:
        """List all wikis available in an Azure DevOps project.

        Args:
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the list of wikis (id, name, remote_url, path).
        """
        try:
            wiki_client = self._get_wiki_client()
            wikis = wiki_client.get_all_wikis(project=self._resolve_project(project))
            data = [
                {
                    "id": wiki.id,
                    "name": wiki.name,
                    "remote_url": wiki.remote_url,
                    "path": wiki.mapped_path,
                }
                for wiki in wikis
            ]
            log_debug(f"Listed {len(data)} Azure DevOps wikis")
            return json.dumps({"wikis": data})
        except Exception as e:
            log_error(f"Error listing Azure DevOps wikis: {e}")
            return json.dumps({"error": str(e)})

    async def aget_wiki_list(self, project: Optional[str] = None) -> str:
        """List all wikis available in an Azure DevOps project (async).

        Args:
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the list of wikis (id, name, remote_url, path).
        """
        return await asyncio.to_thread(self.get_wiki_list, project)

    def get_wiki_pages(
        self,
        wiki_identifier: str,
        path: str = "/",
        project: Optional[str] = None,
    ) -> str:
        """Retrieve a page from a specific Azure DevOps wiki, including its content.

        Args:
            wiki_identifier: The wiki ID or name.
            path: Path of the wiki page. Defaults to the wiki root "/".
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the wiki page details and content.
        """
        try:
            wiki_client = self._get_wiki_client()
            response = wiki_client.get_page(
                project=self._resolve_project(project),
                wiki_identifier=wiki_identifier,
                path=path,
                include_content=True,
            )
            return json.dumps({"wiki_page": _format_wiki_page(response.page)})
        except Exception as e:
            log_error(f"Error getting Azure DevOps wiki page: {e}")
            return json.dumps({"error": str(e)})

    async def aget_wiki_pages(
        self,
        wiki_identifier: str,
        path: str = "/",
        project: Optional[str] = None,
    ) -> str:
        """Retrieve a page from a specific Azure DevOps wiki, including its content (async).

        Args:
            wiki_identifier: The wiki ID or name.
            path: Path of the wiki page. Defaults to the wiki root "/".
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the wiki page details and content.
        """
        return await asyncio.to_thread(self.get_wiki_pages, wiki_identifier, path, project)

    def list_wiki_pages(
        self,
        wiki_identifier: str,
        project: Optional[str] = None,
    ) -> str:
        """List all pages available in a specific Azure DevOps wiki.

        Args:
            wiki_identifier: The wiki ID or name.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the list of pages (path, url, view_stats).
        """
        try:
            data = self._list_wiki_pages(self._resolve_project(project), wiki_identifier)
            return json.dumps({"wiki_pages": data})
        except Exception as e:
            log_error(f"Error listing Azure DevOps wiki pages: {e}")
            return json.dumps({"error": str(e)})

    async def alist_wiki_pages(
        self,
        wiki_identifier: str,
        project: Optional[str] = None,
    ) -> str:
        """List all pages available in a specific Azure DevOps wiki (async).

        Args:
            wiki_identifier: The wiki ID or name.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the list of pages (path, url, view_stats).
        """
        return await asyncio.to_thread(self.list_wiki_pages, wiki_identifier, project)

    def search_in_wiki_pages(
        self,
        wiki_identifier: str,
        search_term: str,
        project: Optional[str] = None,
    ) -> str:
        """Search for pages within a specific Azure DevOps wiki using a text term.

        Args:
            wiki_identifier: The wiki ID or name.
            search_term: Text term to match against page paths and content.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the matching pages (path, url, content_preview).
        """
        try:
            resolved_project = self._resolve_project(project)
            wiki_client = self._get_wiki_client()
            pages = self._list_wiki_pages(resolved_project, wiki_identifier)

            matching_pages = []
            term = search_term.lower()
            for page_info in pages:
                try:
                    response = wiki_client.get_page(
                        project=resolved_project,
                        wiki_identifier=wiki_identifier,
                        path=page_info["path"],
                        include_content=True,
                    )
                    content = response.page.content
                    if term in page_info["path"].lower() or (content and term in content.lower()):
                        matching_pages.append(
                            {
                                "path": page_info["path"],
                                "url": page_info["url"],
                                "content_preview": (
                                    content[:200] + "..." if content and len(content) > 200 else content
                                ),
                            }
                        )
                except Exception:
                    continue

            return json.dumps({"results": matching_pages})
        except Exception as e:
            log_error(f"Error searching Azure DevOps wiki pages: {e}")
            return json.dumps({"error": str(e)})

    async def asearch_in_wiki_pages(
        self,
        wiki_identifier: str,
        search_term: str,
        project: Optional[str] = None,
    ) -> str:
        """Search for pages within a specific Azure DevOps wiki using a text term (async).

        Args:
            wiki_identifier: The wiki ID or name.
            search_term: Text term to match against page paths and content.
            project: Azure DevOps project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string with the matching pages (path, url, content_preview).
        """
        return await asyncio.to_thread(self.search_in_wiki_pages, wiki_identifier, search_term, project)

    def _list_wiki_pages(self, project: str, wiki_identifier: str) -> List[Dict[str, Any]]:
        wiki_client = self._get_wiki_client()
        pages_batch_request = WikiPagesBatchRequest(top=100)
        pages = wiki_client.get_pages_batch(
            project=project,
            wiki_identifier=wiki_identifier,
            pages_batch_request=pages_batch_request,
        )
        return [
            {
                "path": page.path,
                "url": getattr(page, "url", ""),
                "view_stats": (
                    [{"date": stat.date.isoformat(), "count": stat.count} for stat in page.view_stats]
                    if page.view_stats
                    else []
                ),
            }
            for page in pages
        ]
