import json
from os import getenv
from typing import Any, Dict, List, Optional, cast
from urllib.parse import quote_plus

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, logger

try:
    import gitlab
    import httpx
    from gitlab import Gitlab
    from gitlab.exceptions import GitlabAuthenticationError, GitlabError
except ImportError:
    raise ImportError(
        "`python-gitlab` and `httpx` not installed. Please install using `pip install python-gitlab httpx`"
    )


class GitlabTools(Toolkit):
    def __init__(
        self,
        access_token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 30,
        enable_list_projects: bool = True,
        enable_get_projects: bool = True,
        enable_list_merge_requests: bool = True,
        enable_get_merge_request: bool = True,
        enable_list_issues: bool = True,
        **kwargs,
    ):
        self.access_token = access_token or getenv("GITLAB_ACCESS_TOKEN")
        self.base_url = (base_url or getenv("GITLAB_BASE_URL") or "https://gitlab.com").rstrip("/")
        self.timeout = timeout
        self.client: Gitlab = self._create_client()
        self._async_client: Optional[httpx.AsyncClient] = None

        tools: List[Any] = []
        async_tools: List[tuple[Any, str]] = []

        if enable_list_projects:
            tools.append(self.list_projects)
            async_tools.append((self.alist_projects, "list_projects"))
        if enable_get_projects:
            tools.append(self.get_project)
            async_tools.append((self.aget_project, "get_project"))
        if enable_list_merge_requests:
            tools.append(self.list_merge_requests)
            async_tools.append((self.alist_merge_requests, "list_merge_requests"))
        if enable_get_merge_request:
            tools.append(self.get_merge_request)
            async_tools.append((self.aget_merge_request, "get_merge_request"))
        if enable_list_issues:
            tools.append(self.list_issues)
            async_tools.append((self.alist_issues, "list_issues"))

        super().__init__(name="gitlab", tools=tools, async_tools=async_tools, **kwargs)

    def _create_client(self) -> Gitlab:
        """Create and return a GitLab API client."""
        try:
            kwargs: Dict[str, Any] = {"url": self.base_url, "timeout": self.timeout}
            if self.access_token:
                kwargs["private_token"] = self.access_token
            return gitlab.Gitlab(**kwargs)
        except Exception as e:
            raise ValueError(f"Failed to initialize GitLab client: {e}")

    @staticmethod
    def _safe_get(obj: Any, field: str, default: Any = None) -> Any:
        """Return attribute value from object if present."""
        if isinstance(obj, dict):
            return obj.get(field, default)
        return getattr(obj, field, default)

    @staticmethod
    def _bound_page_size(per_page: int) -> int:
        return max(1, min(per_page, 100))

    def _build_meta(self, page: int, per_page: int, returned_items: int) -> Dict[str, int]:
        return {"current_page": page, "per_page": per_page, "returned_items": returned_items}

    def _json_error(self, message: str) -> str:
        return json.dumps({"error": message})

    def _build_headers(self) -> Dict[str, str]:
        if self.access_token:
            return {"PRIVATE-TOKEN": self.access_token}
        return {}

    def _build_api_url(self, endpoint: str) -> str:
        path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        return f"{self.base_url}/api/v4{path}"

    @staticmethod
    def _encode_project_ref(project_id_or_path: str) -> str:
        return quote_plus(str(project_id_or_path), safe="")

    def _http_error_message(self, response: httpx.Response) -> str:
        detail: Optional[str] = None
        try:
            payload = response.json()
            if isinstance(payload, dict):
                message = payload.get("message") or payload.get("error")
                if message is not None:
                    if isinstance(message, (dict, list)):
                        detail = json.dumps(message)
                    else:
                        detail = str(message)
            elif isinstance(payload, list):
                detail = json.dumps(payload)
        except Exception:
            detail = None

        if not detail:
            raw_text = response.text.strip()
            detail = raw_text or response.reason_phrase or "HTTP error"

        return f"{response.status_code}: {detail}"

    def _get_async_client(self) -> httpx.AsyncClient:
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(timeout=self.timeout)
        return self._async_client

    async def _aget(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = self._build_api_url(endpoint)
        headers = self._build_headers()
        client = self._get_async_client()
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        """Close the async HTTP client and release resources."""
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None

    def _get_project(self, project_id_or_path: str):
        return self.client.projects.get(project_id_or_path)

    def _serialize_project(self, project: Any) -> Dict[str, Any]:
        return {
            "id": self._safe_get(project, "id"),
            "name": self._safe_get(project, "name"),
            "path": self._safe_get(project, "path"),
            "path_with_namespace": self._safe_get(project, "path_with_namespace"),
            "description": self._safe_get(project, "description"),
            "web_url": self._safe_get(project, "web_url"),
            "default_branch": self._safe_get(project, "default_branch"),
            "visibility": self._safe_get(project, "visibility"),
            "archived": self._safe_get(project, "archived"),
            "last_activity_at": self._safe_get(project, "last_activity_at"),
        }

    def _serialize_merge_request(self, merge_request: Any) -> Dict[str, Any]:
        author = self._safe_get(merge_request, "author", {}) or {}
        return {
            "id": self._safe_get(merge_request, "id"),
            "iid": self._safe_get(merge_request, "iid"),
            "title": self._safe_get(merge_request, "title"),
            "description": self._safe_get(merge_request, "description"),
            "state": self._safe_get(merge_request, "state"),
            "web_url": self._safe_get(merge_request, "web_url"),
            "source_branch": self._safe_get(merge_request, "source_branch"),
            "target_branch": self._safe_get(merge_request, "target_branch"),
            "author": cast(dict, author).get("username"),
            "created_at": self._safe_get(merge_request, "created_at"),
            "updated_at": self._safe_get(merge_request, "updated_at"),
            "merged_at": self._safe_get(merge_request, "merged_at"),
        }

    def _serialize_issue(self, issue: Any) -> Dict[str, Any]:
        author = self._safe_get(issue, "author", {}) or {}
        assignees = self._safe_get(issue, "assignees", []) or []
        assignee_usernames = [a.get("username") for a in assignees if isinstance(a, dict)]
        return {
            "id": self._safe_get(issue, "id"),
            "iid": self._safe_get(issue, "iid"),
            "title": self._safe_get(issue, "title"),
            "description": self._safe_get(issue, "description"),
            "state": self._safe_get(issue, "state"),
            "labels": self._safe_get(issue, "labels", []),
            "web_url": self._safe_get(issue, "web_url"),
            "author": cast(dict, author).get("username"),
            "assignees": assignee_usernames,
            "created_at": self._safe_get(issue, "created_at"),
            "updated_at": self._safe_get(issue, "updated_at"),
            "due_date": self._safe_get(issue, "due_date"),
        }

    def list_projects(
        self,
        search: Optional[str] = None,
        owned: bool = False,
        membership: bool = False,
        page: int = 1,
        per_page: int = 20,
    ) -> str:
        """
        List projects visible to the authenticated user.

        Args:
            search: Optional search query for project name.
            owned: If True, return only projects owned by the current user.
            membership: If True, return only projects the user is a member of.
            page: Page number for pagination.
            per_page: Items per page (max 100).

        Returns:
            JSON string containing project data and pagination metadata.
        """
        try:
            per_page = self._bound_page_size(per_page)
            params: Dict[str, Any] = {"page": page, "per_page": per_page, "owned": owned, "membership": membership}
            if search:
                params["search"] = search

            log_debug(f"Listing GitLab projects with params: {params}")
            projects = self.client.projects.list(**params)
            data = [self._serialize_project(project) for project in projects]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except (GitlabAuthenticationError, GitlabError) as e:
            logger.exception("GitLab API error while listing projects")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error while listing projects")
            return self._json_error(str(e))

    async def alist_projects(
        self,
        search: Optional[str] = None,
        owned: bool = False,
        membership: bool = False,
        page: int = 1,
        per_page: int = 20,
    ) -> str:
        """
        List projects visible to the authenticated user using async HTTP requests.

        Args:
            search: Optional search query for project name.
            owned: If True, return only projects owned by the current user.
            membership: If True, return only projects the user is a member of.
            page: Page number for pagination.
            per_page: Items per page (max 100).

        Returns:
            JSON string containing project data and pagination metadata.
        """
        try:
            per_page = self._bound_page_size(per_page)
            params: Dict[str, Any] = {"page": page, "per_page": per_page, "owned": owned, "membership": membership}
            if search:
                params["search"] = search

            log_debug(f"Listing GitLab projects with params: {params}")
            projects = await self._aget("/projects", params=params)
            data = [self._serialize_project(project) for project in projects]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"GitLab API error while listing projects: {message}: {str(e)}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.exception("GitLab request error while listing projects")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error while listing projects")
            return self._json_error(str(e))

    def get_project(self, project_id_or_path: str) -> str:
        """
        Get details for a single project.

        Args:
            project_id_or_path: GitLab project ID or URL-encoded path (e.g. group/project).

        Returns:
            JSON string containing project details.
        """
        try:
            log_debug(f"Getting GitLab project: {project_id_or_path}")
            project = self._get_project(project_id_or_path)
            return json.dumps(self._serialize_project(project), indent=2)
        except (GitlabAuthenticationError, GitlabError) as e:
            logger.exception(f"GitLab API error while getting project {project_id_or_path}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while getting project {project_id_or_path}")
            return self._json_error(str(e))

    async def aget_project(self, project_id_or_path: str) -> str:
        """
        Get details for a single project using async HTTP requests.

        Args:
            project_id_or_path: GitLab project ID or URL-encoded path (e.g. group/project).

        Returns:
            JSON string containing project details.
        """
        try:
            project_ref = self._encode_project_ref(project_id_or_path)
            log_debug(f"Getting GitLab project: {project_id_or_path}")
            project = await self._aget(f"/projects/{project_ref}")
            return json.dumps(self._serialize_project(project), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"GitLab API error while getting project {project_id_or_path}: {message}: {str(e)}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.exception(f"GitLab request error while getting project {project_id_or_path}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while getting project {project_id_or_path}")
            return self._json_error(str(e))

    def list_merge_requests(
        self,
        project_id_or_path: str,
        state: str = "opened",
        source_branch: Optional[str] = None,
        target_branch: Optional[str] = None,
        author_username: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> str:
        """
        List merge requests for a project.

        Args:
            project_id_or_path: GitLab project ID or URL-encoded path.
            state: Merge request state (`opened`, `closed`, `merged`, `all`).
            source_branch: Optional source branch filter.
            target_branch: Optional target branch filter.
            author_username: Optional author username filter.
            page: Page number for pagination.
            per_page: Items per page (max 100).

        Returns:
            JSON string containing merge request data and pagination metadata.
        """
        try:
            per_page = self._bound_page_size(per_page)
            project = self._get_project(project_id_or_path)
            params: Dict[str, Any] = {"state": state, "page": page, "per_page": per_page}
            if source_branch:
                params["source_branch"] = source_branch
            if target_branch:
                params["target_branch"] = target_branch
            if author_username:
                params["author_username"] = author_username

            log_debug(f"Listing merge requests for project {project_id_or_path} with params: {params}")
            merge_requests = project.mergerequests.list(**params)
            data = [self._serialize_merge_request(mr) for mr in merge_requests]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except (GitlabAuthenticationError, GitlabError) as e:
            logger.exception(f"GitLab API error while listing merge requests for project {project_id_or_path}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while listing merge requests for project {project_id_or_path}")
            return self._json_error(str(e))

    async def alist_merge_requests(
        self,
        project_id_or_path: str,
        state: str = "opened",
        source_branch: Optional[str] = None,
        target_branch: Optional[str] = None,
        author_username: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> str:
        """
        List merge requests for a project using async HTTP requests.

        Args:
            project_id_or_path: GitLab project ID or URL-encoded path.
            state: Merge request state (`opened`, `closed`, `merged`, `all`).
            source_branch: Optional source branch filter.
            target_branch: Optional target branch filter.
            author_username: Optional author username filter.
            page: Page number for pagination.
            per_page: Items per page (max 100).

        Returns:
            JSON string containing merge request data and pagination metadata.
        """
        try:
            per_page = self._bound_page_size(per_page)
            project_ref = self._encode_project_ref(project_id_or_path)
            params: Dict[str, Any] = {"state": state, "page": page, "per_page": per_page}
            if source_branch:
                params["source_branch"] = source_branch
            if target_branch:
                params["target_branch"] = target_branch
            if author_username:
                params["author_username"] = author_username

            log_debug(f"Listing merge requests for project {project_id_or_path} with params: {params}")
            merge_requests = await self._aget(f"/projects/{project_ref}/merge_requests", params=params)
            data = [self._serialize_merge_request(mr) for mr in merge_requests]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(
                f"GitLab API error while listing merge requests for project {project_id_or_path}: {message}: {str(e)}"
            )
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.exception(f"GitLab request error while listing merge requests for project {project_id_or_path}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while listing merge requests for project {project_id_or_path}")
            return self._json_error(str(e))

    def get_merge_request(self, project_id_or_path: str, merge_request_iid: int) -> str:
        """
        Get details for a single merge request in a project.

        Args:
            project_id_or_path: GitLab project ID or URL-encoded path.
            merge_request_iid: Internal merge request IID in the project.

        Returns:
            JSON string containing merge request details.
        """
        try:
            project = self._get_project(project_id_or_path)
            log_debug(f"Getting merge request {merge_request_iid} from project {project_id_or_path}")
            merge_request = project.mergerequests.get(merge_request_iid)
            return json.dumps(self._serialize_merge_request(merge_request), indent=2)
        except (GitlabAuthenticationError, GitlabError) as e:
            logger.exception(f"GitLab API error while getting merge request {merge_request_iid}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while getting merge request {merge_request_iid}")
            return self._json_error(str(e))

    async def aget_merge_request(self, project_id_or_path: str, merge_request_iid: int) -> str:
        """
        Get details for a single merge request in a project using async HTTP requests.

        Args:
            project_id_or_path: GitLab project ID or URL-encoded path.
            merge_request_iid: Internal merge request IID in the project.

        Returns:
            JSON string containing merge request details.
        """
        try:
            project_ref = self._encode_project_ref(project_id_or_path)
            log_debug(f"Getting merge request {merge_request_iid} from project {project_id_or_path}")
            merge_request = await self._aget(f"/projects/{project_ref}/merge_requests/{merge_request_iid}")
            return json.dumps(self._serialize_merge_request(merge_request), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"GitLab API error while getting merge request {merge_request_iid}: {message}: {str(e)}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.exception(f"GitLab request error while getting merge request {merge_request_iid}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while getting merge request {merge_request_iid}")
            return self._json_error(str(e))

    def list_issues(
        self,
        project_id_or_path: str,
        state: str = "opened",
        labels: Optional[str] = None,
        author_username: Optional[str] = None,
        assignee_username: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> str:
        """
        List issues for a project.

        Args:
            project_id_or_path: GitLab project ID or URL-encoded path.
            state: Issue state (`opened`, `closed`, `all`).
            labels: Optional comma-separated label filter.
            author_username: Optional author username filter.
            assignee_username: Optional assignee username filter.
            search: Optional full-text search query.
            page: Page number for pagination.
            per_page: Items per page (max 100).

        Returns:
            JSON string containing issue data and pagination metadata.
        """
        try:
            per_page = self._bound_page_size(per_page)
            project = self._get_project(project_id_or_path)
            params: Dict[str, Any] = {"state": state, "page": page, "per_page": per_page}
            if labels:
                params["labels"] = labels
            if author_username:
                params["author_username"] = author_username
            if assignee_username:
                params["assignee_username"] = assignee_username
            if search:
                params["search"] = search

            log_debug(f"Listing issues for project {project_id_or_path} with params: {params}")
            issues = project.issues.list(**params)
            data = [self._serialize_issue(issue) for issue in issues]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except (GitlabAuthenticationError, GitlabError) as e:
            logger.exception(f"GitLab API error while listing issues for project {project_id_or_path}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while listing issues for project {project_id_or_path}")
            return self._json_error(str(e))

    async def alist_issues(
        self,
        project_id_or_path: str,
        state: str = "opened",
        labels: Optional[str] = None,
        author_username: Optional[str] = None,
        assignee_username: Optional[str] = None,
        search: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> str:
        """
        List issues for a project using async HTTP requests.

        Args:
            project_id_or_path: GitLab project ID or URL-encoded path.
            state: Issue state (`opened`, `closed`, `all`).
            labels: Optional comma-separated label filter.
            author_username: Optional author username filter.
            assignee_username: Optional assignee username filter.
            search: Optional full-text search query.
            page: Page number for pagination.
            per_page: Items per page (max 100).

        Returns:
            JSON string containing issue data and pagination metadata.
        """
        try:
            per_page = self._bound_page_size(per_page)
            project_ref = self._encode_project_ref(project_id_or_path)
            params: Dict[str, Any] = {"state": state, "page": page, "per_page": per_page}
            if labels:
                params["labels"] = labels
            if author_username:
                params["author_username"] = author_username
            if assignee_username:
                params["assignee_username"] = assignee_username
            if search:
                params["search"] = search

            log_debug(f"Listing issues for project {project_id_or_path} with params: {params}")
            issues = await self._aget(f"/projects/{project_ref}/issues", params=params)
            data = [self._serialize_issue(issue) for issue in issues]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"GitLab API error while listing issues for project {project_id_or_path}: {message}: {str(e)}")
            return self._json_error(message)
        except httpx.RequestError as e:
            logger.exception(f"GitLab request error while listing issues for project {project_id_or_path}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error while listing issues for project {project_id_or_path}")
            return self._json_error(str(e))
