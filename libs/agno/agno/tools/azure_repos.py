import base64
import json
from os import getenv
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, logger

try:
    import httpx
except ImportError:
    raise ImportError("`httpx` not installed. Please install using `pip install httpx`")


_ZERO_OBJECT_ID = "0000000000000000000000000000000000000000"


class AzureReposTools(Toolkit):
    def __init__(
        self,
        organization_url: Optional[str] = None,
        personal_access_token: Optional[str] = None,
        project: Optional[str] = None,
        api_version: str = "7.1",
        timeout: float = 30,
        # Read-only operations (default ON)
        enable_list_repositories: bool = True,
        enable_get_repository: bool = True,
        enable_list_branches: bool = True,
        enable_list_pull_requests: bool = True,
        enable_get_pull_request: bool = True,
        enable_get_pull_request_commits: bool = True,
        enable_list_pull_request_threads: bool = True,
        enable_list_commits: bool = True,
        enable_get_file_content: bool = True,
        enable_list_items: bool = True,
        # Write operations (default ON)
        enable_create_repository: bool = True,
        enable_create_branch: bool = True,
        enable_create_pull_request: bool = True,
        enable_create_pull_request_comment: bool = True,
        # Destructive operations (default OFF)
        enable_delete_repository: bool = False,
        enable_delete_branch: bool = False,
        **kwargs,
    ):
        self.organization_url = (organization_url or getenv("AZURE_DEVOPS_ORG_URL") or "").rstrip("/")
        self.personal_access_token = personal_access_token or getenv("AZURE_DEVOPS_PAT")
        self.project = project or getenv("AZURE_DEVOPS_PROJECT")
        self.api_version = api_version
        self.timeout = timeout

        if not self.organization_url:
            raise ValueError(
                "Azure DevOps organization URL is required. Set AZURE_DEVOPS_ORG_URL or pass `organization_url`."
            )
        if not self.personal_access_token:
            raise ValueError(
                "Azure DevOps personal access token is required. Set AZURE_DEVOPS_PAT or pass `personal_access_token`."
            )

        self._sync_client: Optional[httpx.Client] = None
        self._async_client: Optional[httpx.AsyncClient] = None

        tools: List[Any] = []
        async_tools: List[Tuple[Any, str]] = []

        if enable_list_repositories:
            tools.append(self.list_repositories)
            async_tools.append((self.alist_repositories, "list_repositories"))
        if enable_get_repository:
            tools.append(self.get_repository)
            async_tools.append((self.aget_repository, "get_repository"))
        if enable_list_branches:
            tools.append(self.list_branches)
            async_tools.append((self.alist_branches, "list_branches"))
        if enable_list_pull_requests:
            tools.append(self.list_pull_requests)
            async_tools.append((self.alist_pull_requests, "list_pull_requests"))
        if enable_get_pull_request:
            tools.append(self.get_pull_request)
            async_tools.append((self.aget_pull_request, "get_pull_request"))
        if enable_get_pull_request_commits:
            tools.append(self.get_pull_request_commits)
            async_tools.append((self.aget_pull_request_commits, "get_pull_request_commits"))
        if enable_list_pull_request_threads:
            tools.append(self.list_pull_request_threads)
            async_tools.append((self.alist_pull_request_threads, "list_pull_request_threads"))
        if enable_list_commits:
            tools.append(self.list_commits)
            async_tools.append((self.alist_commits, "list_commits"))
        if enable_get_file_content:
            tools.append(self.get_file_content)
            async_tools.append((self.aget_file_content, "get_file_content"))
        if enable_list_items:
            tools.append(self.list_items)
            async_tools.append((self.alist_items, "list_items"))
        if enable_create_repository:
            tools.append(self.create_repository)
            async_tools.append((self.acreate_repository, "create_repository"))
        if enable_create_branch:
            tools.append(self.create_branch)
            async_tools.append((self.acreate_branch, "create_branch"))
        if enable_create_pull_request:
            tools.append(self.create_pull_request)
            async_tools.append((self.acreate_pull_request, "create_pull_request"))
        if enable_create_pull_request_comment:
            tools.append(self.create_pull_request_comment)
            async_tools.append((self.acreate_pull_request_comment, "create_pull_request_comment"))
        if enable_delete_repository:
            tools.append(self.delete_repository)
            async_tools.append((self.adelete_repository, "delete_repository"))
        if enable_delete_branch:
            tools.append(self.delete_branch)
            async_tools.append((self.adelete_branch, "delete_branch"))

        super().__init__(name="azure_repos", tools=tools, async_tools=async_tools, **kwargs)

    @staticmethod
    def _safe_get(obj: Any, field: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(field, default)
        return getattr(obj, field, default)

    @staticmethod
    def _bound_page_size(per_page: int) -> int:
        return max(1, min(per_page, 100))

    @staticmethod
    def _build_meta(page: int, per_page: int, returned_items: int) -> Dict[str, int]:
        return {"current_page": page, "per_page": per_page, "returned_items": returned_items}

    @staticmethod
    def _json_error(message: str) -> str:
        return json.dumps({"error": message})

    def _resolve_project(self, project: Optional[str]) -> Optional[str]:
        return project or self.project

    def _build_headers(self, content_type: Optional[str] = None) -> Dict[str, str]:
        token = base64.b64encode(f":{self.personal_access_token}".encode("utf-8")).decode("ascii")
        headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _build_url(self, path: str, project: Optional[str] = None) -> str:
        path = path if path.startswith("/") else f"/{path}"
        scope = self._resolve_project(project)
        if scope:
            return f"{self.organization_url}/{quote(scope, safe='')}/_apis{path}"
        return f"{self.organization_url}/_apis{path}"

    def _params_with_version(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        merged: Dict[str, Any] = {"api-version": self.api_version}
        if params:
            for key, value in params.items():
                if value is None:
                    continue
                if isinstance(value, bool):
                    merged[key] = "true" if value else "false"
                else:
                    merged[key] = value
        return merged

    def _http_error_message(self, response: "httpx.Response") -> str:
        detail: Optional[str] = None
        try:
            payload = response.json()
            if isinstance(payload, dict):
                message = payload.get("message") or payload.get("typeKey")
                if message is not None:
                    detail = str(message)
        except Exception:
            detail = None

        if not detail:
            raw_text = response.text.strip()
            detail = raw_text or response.reason_phrase or "HTTP error"

        return f"{response.status_code}: {detail}"

    def _get_sync_client(self) -> "httpx.Client":
        if self._sync_client is None:
            self._sync_client = httpx.Client(timeout=self.timeout)
        return self._sync_client

    def _get_async_client(self) -> "httpx.AsyncClient":
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(timeout=self.timeout)
        return self._async_client

    def _request(
        self,
        method: str,
        path: str,
        project: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        return_text: bool = False,
    ) -> Any:
        url = self._build_url(path, project=project)
        headers = self._build_headers(content_type="application/json" if json_body is not None else None)
        client = self._get_sync_client()
        response = client.request(
            method,
            url,
            params=self._params_with_version(params),
            headers=headers,
            json=json_body,
        )
        response.raise_for_status()
        if return_text:
            return response.text
        if not response.content:
            return None
        try:
            return response.json()
        except Exception:
            return response.text

    async def _arequest(
        self,
        method: str,
        path: str,
        project: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        return_text: bool = False,
    ) -> Any:
        url = self._build_url(path, project=project)
        headers = self._build_headers(content_type="application/json" if json_body is not None else None)
        client = self._get_async_client()
        response = await client.request(
            method,
            url,
            params=self._params_with_version(params),
            headers=headers,
            json=json_body,
        )
        response.raise_for_status()
        if return_text:
            return response.text
        if not response.content:
            return None
        try:
            return response.json()
        except Exception:
            return response.text

    def close(self) -> None:
        """Close the sync HTTP client and release resources."""
        if self._sync_client is not None:
            self._sync_client.close()
            self._sync_client = None

    async def aclose(self) -> None:
        """Close the async HTTP client and release resources."""
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None

    def _serialize_repository(self, repo: Any) -> Dict[str, Any]:
        project = self._safe_get(repo, "project", {}) or {}
        return {
            "id": self._safe_get(repo, "id"),
            "name": self._safe_get(repo, "name"),
            "url": self._safe_get(repo, "url"),
            "web_url": self._safe_get(repo, "webUrl"),
            "default_branch": self._safe_get(repo, "defaultBranch"),
            "size": self._safe_get(repo, "size"),
            "is_disabled": self._safe_get(repo, "isDisabled"),
            "project": {
                "id": self._safe_get(project, "id"),
                "name": self._safe_get(project, "name"),
            }
            if project
            else None,
        }

    def _serialize_branch(self, ref: Any) -> Dict[str, Any]:
        name = self._safe_get(ref, "name") or ""
        return {
            "name": name,
            "short_name": name.replace("refs/heads/", "", 1) if name.startswith("refs/heads/") else name,
            "object_id": self._safe_get(ref, "objectId"),
            "creator": self._safe_get(self._safe_get(ref, "creator", {}) or {}, "displayName"),
            "url": self._safe_get(ref, "url"),
        }

    def _serialize_pull_request(self, pr: Any) -> Dict[str, Any]:
        created_by = self._safe_get(pr, "createdBy", {}) or {}
        repo = self._safe_get(pr, "repository", {}) or {}
        return {
            "id": self._safe_get(pr, "pullRequestId"),
            "title": self._safe_get(pr, "title"),
            "description": self._safe_get(pr, "description"),
            "status": self._safe_get(pr, "status"),
            "is_draft": self._safe_get(pr, "isDraft"),
            "merge_status": self._safe_get(pr, "mergeStatus"),
            "source_branch": self._safe_get(pr, "sourceRefName"),
            "target_branch": self._safe_get(pr, "targetRefName"),
            "created_by": self._safe_get(created_by, "displayName"),
            "created_at": self._safe_get(pr, "creationDate"),
            "closed_at": self._safe_get(pr, "closedDate"),
            "url": self._safe_get(pr, "url"),
            "repository": {
                "id": self._safe_get(repo, "id"),
                "name": self._safe_get(repo, "name"),
            }
            if repo
            else None,
        }

    def _serialize_commit(self, commit: Any) -> Dict[str, Any]:
        author = self._safe_get(commit, "author", {}) or {}
        committer = self._safe_get(commit, "committer", {}) or {}
        return {
            "commit_id": self._safe_get(commit, "commitId"),
            "comment": self._safe_get(commit, "comment"),
            "author": {
                "name": self._safe_get(author, "name"),
                "email": self._safe_get(author, "email"),
                "date": self._safe_get(author, "date"),
            },
            "committer": {
                "name": self._safe_get(committer, "name"),
                "email": self._safe_get(committer, "email"),
                "date": self._safe_get(committer, "date"),
            },
            "url": self._safe_get(commit, "url"),
        }

    def _serialize_thread(self, thread: Any) -> Dict[str, Any]:
        comments_raw = self._safe_get(thread, "comments", []) or []
        comments = [
            {
                "id": self._safe_get(c, "id"),
                "content": self._safe_get(c, "content"),
                "author": self._safe_get(self._safe_get(c, "author", {}) or {}, "displayName"),
                "published_date": self._safe_get(c, "publishedDate"),
            }
            for c in comments_raw
        ]
        return {
            "id": self._safe_get(thread, "id"),
            "status": self._safe_get(thread, "status"),
            "is_deleted": self._safe_get(thread, "isDeleted"),
            "published_date": self._safe_get(thread, "publishedDate"),
            "last_updated_date": self._safe_get(thread, "lastUpdatedDate"),
            "comments": comments,
        }

    def _serialize_item(self, item: Any) -> Dict[str, Any]:
        return {
            "path": self._safe_get(item, "path"),
            "object_id": self._safe_get(item, "objectId"),
            "git_object_type": self._safe_get(item, "gitObjectType"),
            "is_folder": self._safe_get(item, "isFolder"),
            "size": self._safe_get(item, "size"),
            "url": self._safe_get(item, "url"),
        }

    def list_repositories(self, project: Optional[str] = None) -> str:
        """List Git repositories in the organization or a specific project.

        Args:
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with a `data` array of repositories and pagination metadata.
        """
        try:
            log_debug(f"Listing Azure DevOps repositories for project: {project or self.project}")
            payload = self._request("GET", "/git/repositories", project=project)
            repos = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            data = [self._serialize_repository(repo) for repo in repos]
            return json.dumps({"data": data, "meta": self._build_meta(1, len(data), len(data))}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while listing repositories: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while listing repositories")
            return self._json_error(str(e))

    async def alist_repositories(self, project: Optional[str] = None) -> str:
        """List Git repositories using async HTTP requests.

        Args:
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with a `data` array of repositories and pagination metadata.
        """
        try:
            log_debug(f"Listing Azure DevOps repositories for project: {project or self.project}")
            payload = await self._arequest("GET", "/git/repositories", project=project)
            repos = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            data = [self._serialize_repository(repo) for repo in repos]
            return json.dumps({"data": data, "meta": self._build_meta(1, len(data), len(data))}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while listing repositories: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while listing repositories")
            return self._json_error(str(e))

    def get_repository(self, repository: str, project: Optional[str] = None) -> str:
        """Get details for a single Git repository.

        Args:
            repository: Repository ID or name.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string containing repository details.
        """
        try:
            log_debug(f"Getting Azure DevOps repository: {repository}")
            repo = self._request("GET", f"/git/repositories/{quote(repository, safe='')}", project=project)
            return json.dumps(self._serialize_repository(repo or {}), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while getting repository {repository}: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception(f"Unexpected error while getting repository {repository}")
            return self._json_error(str(e))

    async def aget_repository(self, repository: str, project: Optional[str] = None) -> str:
        """Get details for a single Git repository using async HTTP requests.

        Args:
            repository: Repository ID or name.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string containing repository details.
        """
        try:
            log_debug(f"Getting Azure DevOps repository: {repository}")
            repo = await self._arequest("GET", f"/git/repositories/{quote(repository, safe='')}", project=project)
            return json.dumps(self._serialize_repository(repo or {}), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while getting repository {repository}: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception(f"Unexpected error while getting repository {repository}")
            return self._json_error(str(e))

    def create_repository(self, name: str, project: Optional[str] = None) -> str:
        """Create a new Git repository inside a project.

        Args:
            name: New repository name.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string containing the created repository details.
        """
        scope = self._resolve_project(project)
        if not scope:
            return self._json_error("`project` is required to create a repository")
        body = {"name": name, "project": {"name": scope}}
        try:
            log_debug(f"Creating Azure DevOps repository: {name} in project {scope}")
            repo = self._request("POST", "/git/repositories", project=scope, json_body=body)
            return json.dumps(self._serialize_repository(repo or {}), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while creating repository {name}: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception(f"Unexpected error while creating repository {name}")
            return self._json_error(str(e))

    async def acreate_repository(self, name: str, project: Optional[str] = None) -> str:
        """Create a new Git repository using async HTTP requests.

        Args:
            name: New repository name.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string containing the created repository details.
        """
        scope = self._resolve_project(project)
        if not scope:
            return self._json_error("`project` is required to create a repository")
        body = {"name": name, "project": {"name": scope}}
        try:
            log_debug(f"Creating Azure DevOps repository: {name} in project {scope}")
            repo = await self._arequest("POST", "/git/repositories", project=scope, json_body=body)
            return json.dumps(self._serialize_repository(repo or {}), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while creating repository {name}: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception(f"Unexpected error while creating repository {name}")
            return self._json_error(str(e))

    def delete_repository(self, repository: str, project: Optional[str] = None) -> str:
        """Delete a Git repository (irreversible).

        Args:
            repository: Repository ID or name.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string confirming deletion or describing the error.
        """
        try:
            log_debug(f"Deleting Azure DevOps repository: {repository}")
            self._request("DELETE", f"/git/repositories/{quote(repository, safe='')}", project=project)
            return json.dumps({"message": f"Repository {repository} deleted."}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while deleting repository {repository}: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception(f"Unexpected error while deleting repository {repository}")
            return self._json_error(str(e))

    async def adelete_repository(self, repository: str, project: Optional[str] = None) -> str:
        """Delete a Git repository using async HTTP requests (irreversible).

        Args:
            repository: Repository ID or name.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string confirming deletion or describing the error.
        """
        try:
            log_debug(f"Deleting Azure DevOps repository: {repository}")
            await self._arequest("DELETE", f"/git/repositories/{quote(repository, safe='')}", project=project)
            return json.dumps({"message": f"Repository {repository} deleted."}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while deleting repository {repository}: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception(f"Unexpected error while deleting repository {repository}")
            return self._json_error(str(e))

    def list_branches(self, repository: str, project: Optional[str] = None) -> str:
        """List branches (heads) in a repository.

        Args:
            repository: Repository ID or name.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with a `data` array of branches and pagination metadata.
        """
        try:
            log_debug(f"Listing branches for repository: {repository}")
            payload = self._request(
                "GET",
                f"/git/repositories/{quote(repository, safe='')}/refs",
                project=project,
                params={"filter": "heads/"},
            )
            refs = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            data = [self._serialize_branch(ref) for ref in refs]
            return json.dumps({"data": data, "meta": self._build_meta(1, len(data), len(data))}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while listing branches: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while listing branches")
            return self._json_error(str(e))

    async def alist_branches(self, repository: str, project: Optional[str] = None) -> str:
        """List branches in a repository using async HTTP requests.

        Args:
            repository: Repository ID or name.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with a `data` array of branches and pagination metadata.
        """
        try:
            log_debug(f"Listing branches for repository: {repository}")
            payload = await self._arequest(
                "GET",
                f"/git/repositories/{quote(repository, safe='')}/refs",
                project=project,
                params={"filter": "heads/"},
            )
            refs = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            data = [self._serialize_branch(ref) for ref in refs]
            return json.dumps({"data": data, "meta": self._build_meta(1, len(data), len(data))}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while listing branches: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while listing branches")
            return self._json_error(str(e))

    def _resolve_source_object_id(self, repository: str, source_branch: Optional[str], project: Optional[str]) -> str:
        """Look up the object ID of the source branch (or the repo's default branch)."""
        path = f"/git/repositories/{quote(repository, safe='')}/refs"
        if source_branch:
            short = source_branch.replace("refs/heads/", "", 1)
            payload = self._request("GET", path, project=project, params={"filter": f"heads/{short}"})
        else:
            repo_payload = self._request("GET", f"/git/repositories/{quote(repository, safe='')}", project=project)
            default_branch = (repo_payload or {}).get("defaultBranch")
            if not default_branch:
                raise ValueError(f"Repository {repository} has no default branch to use as source")
            short = default_branch.replace("refs/heads/", "", 1)
            payload = self._request("GET", path, project=project, params={"filter": f"heads/{short}"})
        refs = (payload or {}).get("value", []) if isinstance(payload, dict) else []
        if not refs:
            raise ValueError(f"Source branch not found in repository {repository}")
        return refs[0].get("objectId", "")

    async def _aresolve_source_object_id(
        self, repository: str, source_branch: Optional[str], project: Optional[str]
    ) -> str:
        path = f"/git/repositories/{quote(repository, safe='')}/refs"
        if source_branch:
            short = source_branch.replace("refs/heads/", "", 1)
            payload = await self._arequest("GET", path, project=project, params={"filter": f"heads/{short}"})
        else:
            repo_payload = await self._arequest(
                "GET", f"/git/repositories/{quote(repository, safe='')}", project=project
            )
            default_branch = (repo_payload or {}).get("defaultBranch")
            if not default_branch:
                raise ValueError(f"Repository {repository} has no default branch to use as source")
            short = default_branch.replace("refs/heads/", "", 1)
            payload = await self._arequest("GET", path, project=project, params={"filter": f"heads/{short}"})
        refs = (payload or {}).get("value", []) if isinstance(payload, dict) else []
        if not refs:
            raise ValueError(f"Source branch not found in repository {repository}")
        return refs[0].get("objectId", "")

    def create_branch(
        self,
        repository: str,
        branch_name: str,
        source_branch: Optional[str] = None,
        project: Optional[str] = None,
    ) -> str:
        """Create a new branch from a source branch (or from the repository's default branch).

        Args:
            repository: Repository ID or name.
            branch_name: New branch name (without `refs/heads/` prefix).
            source_branch: Optional source branch. Defaults to the repository's default branch.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with the created ref details.
        """
        try:
            log_debug(f"Creating branch {branch_name} in repository: {repository}")
            old_object_id = self._resolve_source_object_id(repository, source_branch, project)
            full_name = branch_name if branch_name.startswith("refs/heads/") else f"refs/heads/{branch_name}"
            body = [{"name": full_name, "oldObjectId": _ZERO_OBJECT_ID, "newObjectId": old_object_id}]
            payload = self._request(
                "POST",
                f"/git/repositories/{quote(repository, safe='')}/refs",
                project=project,
                json_body=body,
            )
            results = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            result = results[0] if results else {}
            return json.dumps(
                {
                    "name": result.get("name", full_name),
                    "object_id": result.get("newObjectId") or old_object_id,
                    "success": result.get("success", True),
                },
                indent=2,
            )
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while creating branch {branch_name}: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception(f"Unexpected error while creating branch {branch_name}")
            return self._json_error(str(e))

    async def acreate_branch(
        self,
        repository: str,
        branch_name: str,
        source_branch: Optional[str] = None,
        project: Optional[str] = None,
    ) -> str:
        """Create a branch using async HTTP requests.

        Args:
            repository: Repository ID or name.
            branch_name: New branch name (without `refs/heads/` prefix).
            source_branch: Optional source branch. Defaults to the repository's default branch.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with the created ref details.
        """
        try:
            log_debug(f"Creating branch {branch_name} in repository: {repository}")
            old_object_id = await self._aresolve_source_object_id(repository, source_branch, project)
            full_name = branch_name if branch_name.startswith("refs/heads/") else f"refs/heads/{branch_name}"
            body = [{"name": full_name, "oldObjectId": _ZERO_OBJECT_ID, "newObjectId": old_object_id}]
            payload = await self._arequest(
                "POST",
                f"/git/repositories/{quote(repository, safe='')}/refs",
                project=project,
                json_body=body,
            )
            results = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            result = results[0] if results else {}
            return json.dumps(
                {
                    "name": result.get("name", full_name),
                    "object_id": result.get("newObjectId") or old_object_id,
                    "success": result.get("success", True),
                },
                indent=2,
            )
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while creating branch {branch_name}: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception(f"Unexpected error while creating branch {branch_name}")
            return self._json_error(str(e))

    def delete_branch(
        self,
        repository: str,
        branch_name: str,
        project: Optional[str] = None,
    ) -> str:
        """Delete a branch by setting its newObjectId to zero (irreversible).

        Args:
            repository: Repository ID or name.
            branch_name: Branch name to delete (without `refs/heads/` prefix).
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string confirming deletion or describing the error.
        """
        try:
            log_debug(f"Deleting branch {branch_name} in repository: {repository}")
            full_name = branch_name if branch_name.startswith("refs/heads/") else f"refs/heads/{branch_name}"
            short = full_name.replace("refs/heads/", "", 1)
            payload = self._request(
                "GET",
                f"/git/repositories/{quote(repository, safe='')}/refs",
                project=project,
                params={"filter": f"heads/{short}"},
            )
            refs = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            if not refs:
                return self._json_error(f"Branch {branch_name} not found")
            old_object_id = refs[0].get("objectId", "")
            body = [{"name": full_name, "oldObjectId": old_object_id, "newObjectId": _ZERO_OBJECT_ID}]
            self._request(
                "POST",
                f"/git/repositories/{quote(repository, safe='')}/refs",
                project=project,
                json_body=body,
            )
            return json.dumps({"message": f"Branch {branch_name} deleted."}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while deleting branch {branch_name}: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception(f"Unexpected error while deleting branch {branch_name}")
            return self._json_error(str(e))

    async def adelete_branch(
        self,
        repository: str,
        branch_name: str,
        project: Optional[str] = None,
    ) -> str:
        """Delete a branch using async HTTP requests (irreversible).

        Args:
            repository: Repository ID or name.
            branch_name: Branch name to delete (without `refs/heads/` prefix).
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string confirming deletion or describing the error.
        """
        try:
            log_debug(f"Deleting branch {branch_name} in repository: {repository}")
            full_name = branch_name if branch_name.startswith("refs/heads/") else f"refs/heads/{branch_name}"
            short = full_name.replace("refs/heads/", "", 1)
            payload = await self._arequest(
                "GET",
                f"/git/repositories/{quote(repository, safe='')}/refs",
                project=project,
                params={"filter": f"heads/{short}"},
            )
            refs = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            if not refs:
                return self._json_error(f"Branch {branch_name} not found")
            old_object_id = refs[0].get("objectId", "")
            body = [{"name": full_name, "oldObjectId": old_object_id, "newObjectId": _ZERO_OBJECT_ID}]
            await self._arequest(
                "POST",
                f"/git/repositories/{quote(repository, safe='')}/refs",
                project=project,
                json_body=body,
            )
            return json.dumps({"message": f"Branch {branch_name} deleted."}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while deleting branch {branch_name}: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception(f"Unexpected error while deleting branch {branch_name}")
            return self._json_error(str(e))

    def _build_pr_search_params(
        self,
        status: str,
        source_branch: Optional[str],
        target_branch: Optional[str],
        creator_id: Optional[str],
        page: int,
        per_page: int,
    ) -> Dict[str, Any]:
        per_page = self._bound_page_size(per_page)
        params: Dict[str, Any] = {
            "searchCriteria.status": status,
            "$top": per_page,
            "$skip": max(0, (page - 1) * per_page),
        }
        if source_branch:
            params["searchCriteria.sourceRefName"] = (
                source_branch if source_branch.startswith("refs/heads/") else f"refs/heads/{source_branch}"
            )
        if target_branch:
            params["searchCriteria.targetRefName"] = (
                target_branch if target_branch.startswith("refs/heads/") else f"refs/heads/{target_branch}"
            )
        if creator_id:
            params["searchCriteria.creatorId"] = creator_id
        return params

    def list_pull_requests(
        self,
        repository: str,
        status: str = "active",
        source_branch: Optional[str] = None,
        target_branch: Optional[str] = None,
        creator_id: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
        project: Optional[str] = None,
    ) -> str:
        """List pull requests for a repository.

        Args:
            repository: Repository ID or name.
            status: One of `active`, `abandoned`, `completed`, `all`.
            source_branch: Optional source branch filter (with or without `refs/heads/` prefix).
            target_branch: Optional target branch filter (with or without `refs/heads/` prefix).
            creator_id: Optional creator user descriptor or GUID.
            page: Page number (1-indexed).
            per_page: Items per page (max 100).
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with a `data` array of pull requests and pagination metadata.
        """
        try:
            params = self._build_pr_search_params(status, source_branch, target_branch, creator_id, page, per_page)
            log_debug(f"Listing pull requests for repository {repository} with params: {params}")
            payload = self._request(
                "GET",
                f"/git/repositories/{quote(repository, safe='')}/pullrequests",
                project=project,
                params=params,
            )
            prs = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            data = [self._serialize_pull_request(pr) for pr in prs]
            return json.dumps(
                {"data": data, "meta": self._build_meta(page, self._bound_page_size(per_page), len(data))},
                indent=2,
            )
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while listing pull requests: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while listing pull requests")
            return self._json_error(str(e))

    async def alist_pull_requests(
        self,
        repository: str,
        status: str = "active",
        source_branch: Optional[str] = None,
        target_branch: Optional[str] = None,
        creator_id: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
        project: Optional[str] = None,
    ) -> str:
        """List pull requests using async HTTP requests.

        Args:
            repository: Repository ID or name.
            status: One of `active`, `abandoned`, `completed`, `all`.
            source_branch: Optional source branch filter (with or without `refs/heads/` prefix).
            target_branch: Optional target branch filter (with or without `refs/heads/` prefix).
            creator_id: Optional creator user descriptor or GUID.
            page: Page number (1-indexed).
            per_page: Items per page (max 100).
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with a `data` array of pull requests and pagination metadata.
        """
        try:
            params = self._build_pr_search_params(status, source_branch, target_branch, creator_id, page, per_page)
            log_debug(f"Listing pull requests for repository {repository} with params: {params}")
            payload = await self._arequest(
                "GET",
                f"/git/repositories/{quote(repository, safe='')}/pullrequests",
                project=project,
                params=params,
            )
            prs = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            data = [self._serialize_pull_request(pr) for pr in prs]
            return json.dumps(
                {"data": data, "meta": self._build_meta(page, self._bound_page_size(per_page), len(data))},
                indent=2,
            )
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while listing pull requests: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while listing pull requests")
            return self._json_error(str(e))

    def get_pull_request(self, pull_request_id: int, project: Optional[str] = None) -> str:
        """Get details for a single pull request by ID.

        Args:
            pull_request_id: The numeric pull request ID.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string containing pull request details.
        """
        try:
            log_debug(f"Getting pull request {pull_request_id}")
            pr = self._request("GET", f"/git/pullrequests/{pull_request_id}", project=project)
            return json.dumps(self._serialize_pull_request(pr or {}), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while getting pull request {pull_request_id}: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception(f"Unexpected error while getting pull request {pull_request_id}")
            return self._json_error(str(e))

    async def aget_pull_request(self, pull_request_id: int, project: Optional[str] = None) -> str:
        """Get details for a single pull request using async HTTP requests.

        Args:
            pull_request_id: The numeric pull request ID.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string containing pull request details.
        """
        try:
            log_debug(f"Getting pull request {pull_request_id}")
            pr = await self._arequest("GET", f"/git/pullrequests/{pull_request_id}", project=project)
            return json.dumps(self._serialize_pull_request(pr or {}), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while getting pull request {pull_request_id}: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception(f"Unexpected error while getting pull request {pull_request_id}")
            return self._json_error(str(e))

    def create_pull_request(
        self,
        repository: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: Optional[str] = None,
        is_draft: bool = False,
        project: Optional[str] = None,
    ) -> str:
        """Create a new pull request.

        Args:
            repository: Repository ID or name.
            source_branch: Source branch (with or without `refs/heads/` prefix).
            target_branch: Target branch (with or without `refs/heads/` prefix).
            title: Pull request title.
            description: Optional pull request description.
            is_draft: Whether to create as draft.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string containing the created pull request details.
        """
        body = {
            "sourceRefName": source_branch
            if source_branch.startswith("refs/heads/")
            else f"refs/heads/{source_branch}",
            "targetRefName": target_branch
            if target_branch.startswith("refs/heads/")
            else f"refs/heads/{target_branch}",
            "title": title,
            "description": description or "",
            "isDraft": is_draft,
        }
        try:
            log_debug(f"Creating pull request {source_branch} -> {target_branch} in {repository}")
            pr = self._request(
                "POST",
                f"/git/repositories/{quote(repository, safe='')}/pullrequests",
                project=project,
                json_body=body,
            )
            return json.dumps(self._serialize_pull_request(pr or {}), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while creating pull request: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while creating pull request")
            return self._json_error(str(e))

    async def acreate_pull_request(
        self,
        repository: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: Optional[str] = None,
        is_draft: bool = False,
        project: Optional[str] = None,
    ) -> str:
        """Create a pull request using async HTTP requests.

        Args:
            repository: Repository ID or name.
            source_branch: Source branch (with or without `refs/heads/` prefix).
            target_branch: Target branch (with or without `refs/heads/` prefix).
            title: Pull request title.
            description: Optional pull request description.
            is_draft: Whether to create as draft.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string containing the created pull request details.
        """
        body = {
            "sourceRefName": source_branch
            if source_branch.startswith("refs/heads/")
            else f"refs/heads/{source_branch}",
            "targetRefName": target_branch
            if target_branch.startswith("refs/heads/")
            else f"refs/heads/{target_branch}",
            "title": title,
            "description": description or "",
            "isDraft": is_draft,
        }
        try:
            log_debug(f"Creating pull request {source_branch} -> {target_branch} in {repository}")
            pr = await self._arequest(
                "POST",
                f"/git/repositories/{quote(repository, safe='')}/pullrequests",
                project=project,
                json_body=body,
            )
            return json.dumps(self._serialize_pull_request(pr or {}), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while creating pull request: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while creating pull request")
            return self._json_error(str(e))

    def get_pull_request_commits(self, repository: str, pull_request_id: int, project: Optional[str] = None) -> str:
        """List commits associated with a pull request.

        Args:
            repository: Repository ID or name.
            pull_request_id: The numeric pull request ID.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with a `data` array of commits and pagination metadata.
        """
        try:
            log_debug(f"Getting commits for PR {pull_request_id} in {repository}")
            payload = self._request(
                "GET",
                f"/git/repositories/{quote(repository, safe='')}/pullrequests/{pull_request_id}/commits",
                project=project,
            )
            commits = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            data = [self._serialize_commit(c) for c in commits]
            return json.dumps({"data": data, "meta": self._build_meta(1, len(data), len(data))}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while getting PR commits: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while getting PR commits")
            return self._json_error(str(e))

    async def aget_pull_request_commits(
        self, repository: str, pull_request_id: int, project: Optional[str] = None
    ) -> str:
        """List commits associated with a pull request using async HTTP requests.

        Args:
            repository: Repository ID or name.
            pull_request_id: The numeric pull request ID.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with a `data` array of commits and pagination metadata.
        """
        try:
            log_debug(f"Getting commits for PR {pull_request_id} in {repository}")
            payload = await self._arequest(
                "GET",
                f"/git/repositories/{quote(repository, safe='')}/pullrequests/{pull_request_id}/commits",
                project=project,
            )
            commits = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            data = [self._serialize_commit(c) for c in commits]
            return json.dumps({"data": data, "meta": self._build_meta(1, len(data), len(data))}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while getting PR commits: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while getting PR commits")
            return self._json_error(str(e))

    def list_pull_request_threads(self, repository: str, pull_request_id: int, project: Optional[str] = None) -> str:
        """List comment threads on a pull request.

        Args:
            repository: Repository ID or name.
            pull_request_id: The numeric pull request ID.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with a `data` array of threads and pagination metadata.
        """
        try:
            log_debug(f"Listing threads for PR {pull_request_id} in {repository}")
            payload = self._request(
                "GET",
                f"/git/repositories/{quote(repository, safe='')}/pullrequests/{pull_request_id}/threads",
                project=project,
            )
            threads = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            data = [self._serialize_thread(t) for t in threads]
            return json.dumps({"data": data, "meta": self._build_meta(1, len(data), len(data))}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while listing PR threads: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while listing PR threads")
            return self._json_error(str(e))

    async def alist_pull_request_threads(
        self, repository: str, pull_request_id: int, project: Optional[str] = None
    ) -> str:
        """List PR comment threads using async HTTP requests.

        Args:
            repository: Repository ID or name.
            pull_request_id: The numeric pull request ID.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with a `data` array of threads and pagination metadata.
        """
        try:
            log_debug(f"Listing threads for PR {pull_request_id} in {repository}")
            payload = await self._arequest(
                "GET",
                f"/git/repositories/{quote(repository, safe='')}/pullrequests/{pull_request_id}/threads",
                project=project,
            )
            threads = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            data = [self._serialize_thread(t) for t in threads]
            return json.dumps({"data": data, "meta": self._build_meta(1, len(data), len(data))}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while listing PR threads: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while listing PR threads")
            return self._json_error(str(e))

    def create_pull_request_comment(
        self,
        repository: str,
        pull_request_id: int,
        content: str,
        project: Optional[str] = None,
    ) -> str:
        """Create a new comment thread on a pull request.

        Args:
            repository: Repository ID or name.
            pull_request_id: The numeric pull request ID.
            content: The comment text.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string containing the created thread details.
        """
        body = {
            "comments": [{"parentCommentId": 0, "content": content, "commentType": "text"}],
            "status": "active",
        }
        try:
            log_debug(f"Creating comment on PR {pull_request_id} in {repository}")
            thread = self._request(
                "POST",
                f"/git/repositories/{quote(repository, safe='')}/pullrequests/{pull_request_id}/threads",
                project=project,
                json_body=body,
            )
            return json.dumps(self._serialize_thread(thread or {}), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while creating PR comment: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while creating PR comment")
            return self._json_error(str(e))

    async def acreate_pull_request_comment(
        self,
        repository: str,
        pull_request_id: int,
        content: str,
        project: Optional[str] = None,
    ) -> str:
        """Create a comment thread on a pull request using async HTTP requests.

        Args:
            repository: Repository ID or name.
            pull_request_id: The numeric pull request ID.
            content: The comment text.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string containing the created thread details.
        """
        body = {
            "comments": [{"parentCommentId": 0, "content": content, "commentType": "text"}],
            "status": "active",
        }
        try:
            log_debug(f"Creating comment on PR {pull_request_id} in {repository}")
            thread = await self._arequest(
                "POST",
                f"/git/repositories/{quote(repository, safe='')}/pullrequests/{pull_request_id}/threads",
                project=project,
                json_body=body,
            )
            return json.dumps(self._serialize_thread(thread or {}), indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while creating PR comment: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while creating PR comment")
            return self._json_error(str(e))

    def list_commits(
        self,
        repository: str,
        branch: Optional[str] = None,
        author: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
        project: Optional[str] = None,
    ) -> str:
        """List commits in a repository.

        Args:
            repository: Repository ID or name.
            branch: Optional branch filter (with or without `refs/heads/` prefix).
            author: Optional author email filter.
            page: Page number (1-indexed).
            per_page: Items per page (max 100).
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with a `data` array of commits and pagination metadata.
        """
        per_page = self._bound_page_size(per_page)
        params: Dict[str, Any] = {"$top": per_page, "$skip": max(0, (page - 1) * per_page)}
        if branch:
            short = branch.replace("refs/heads/", "", 1)
            params["searchCriteria.itemVersion.version"] = short
            params["searchCriteria.itemVersion.versionType"] = "branch"
        if author:
            params["searchCriteria.author"] = author
        try:
            log_debug(f"Listing commits for repository {repository} with params: {params}")
            payload = self._request(
                "GET",
                f"/git/repositories/{quote(repository, safe='')}/commits",
                project=project,
                params=params,
            )
            commits = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            data = [self._serialize_commit(c) for c in commits]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while listing commits: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while listing commits")
            return self._json_error(str(e))

    async def alist_commits(
        self,
        repository: str,
        branch: Optional[str] = None,
        author: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
        project: Optional[str] = None,
    ) -> str:
        """List commits using async HTTP requests.

        Args:
            repository: Repository ID or name.
            branch: Optional branch filter (with or without `refs/heads/` prefix).
            author: Optional author email filter.
            page: Page number (1-indexed).
            per_page: Items per page (max 100).
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with a `data` array of commits and pagination metadata.
        """
        per_page = self._bound_page_size(per_page)
        params: Dict[str, Any] = {"$top": per_page, "$skip": max(0, (page - 1) * per_page)}
        if branch:
            short = branch.replace("refs/heads/", "", 1)
            params["searchCriteria.itemVersion.version"] = short
            params["searchCriteria.itemVersion.versionType"] = "branch"
        if author:
            params["searchCriteria.author"] = author
        try:
            log_debug(f"Listing commits for repository {repository} with params: {params}")
            payload = await self._arequest(
                "GET",
                f"/git/repositories/{quote(repository, safe='')}/commits",
                project=project,
                params=params,
            )
            commits = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            data = [self._serialize_commit(c) for c in commits]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while listing commits: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while listing commits")
            return self._json_error(str(e))

    def get_file_content(
        self,
        repository: str,
        path: str,
        branch: Optional[str] = None,
        project: Optional[str] = None,
    ) -> str:
        """Get the raw text content of a file in a repository.

        Args:
            repository: Repository ID or name.
            path: File path inside the repository (e.g. `/README.md`).
            branch: Optional branch (with or without `refs/heads/` prefix). Defaults to the repo's default branch.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with `path`, `branch`, and `content` fields.
        """
        params: Dict[str, Any] = {
            "path": path,
            "includeContent": True,
            "$format": "json",
        }
        if branch:
            short = branch.replace("refs/heads/", "", 1)
            params["versionDescriptor.version"] = short
            params["versionDescriptor.versionType"] = "branch"
        try:
            log_debug(f"Getting file content for {path} in {repository}")
            payload = self._request(
                "GET",
                f"/git/repositories/{quote(repository, safe='')}/items",
                project=project,
                params=params,
            )
            content = ""
            if isinstance(payload, dict):
                content = payload.get("content", "") or ""
            elif isinstance(payload, str):
                content = payload
            return json.dumps({"path": path, "branch": branch, "content": content}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while getting file {path}: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception(f"Unexpected error while getting file {path}")
            return self._json_error(str(e))

    async def aget_file_content(
        self,
        repository: str,
        path: str,
        branch: Optional[str] = None,
        project: Optional[str] = None,
    ) -> str:
        """Get the raw text content of a file using async HTTP requests.

        Args:
            repository: Repository ID or name.
            path: File path inside the repository (e.g. `/README.md`).
            branch: Optional branch (with or without `refs/heads/` prefix). Defaults to the repo's default branch.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with `path`, `branch`, and `content` fields.
        """
        params: Dict[str, Any] = {
            "path": path,
            "includeContent": True,
            "$format": "json",
        }
        if branch:
            short = branch.replace("refs/heads/", "", 1)
            params["versionDescriptor.version"] = short
            params["versionDescriptor.versionType"] = "branch"
        try:
            log_debug(f"Getting file content for {path} in {repository}")
            payload = await self._arequest(
                "GET",
                f"/git/repositories/{quote(repository, safe='')}/items",
                project=project,
                params=params,
            )
            content = ""
            if isinstance(payload, dict):
                content = payload.get("content", "") or ""
            elif isinstance(payload, str):
                content = payload
            return json.dumps({"path": path, "branch": branch, "content": content}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while getting file {path}: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception(f"Unexpected error while getting file {path}")
            return self._json_error(str(e))

    def list_items(
        self,
        repository: str,
        path: str = "/",
        branch: Optional[str] = None,
        recursion_level: str = "oneLevel",
        project: Optional[str] = None,
    ) -> str:
        """List items (files and folders) under a repository path.

        Args:
            repository: Repository ID or name.
            path: Directory path inside the repository. Defaults to repo root.
            branch: Optional branch (with or without `refs/heads/` prefix). Defaults to the repo's default branch.
            recursion_level: One of `none`, `oneLevel`, `full`.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with a `data` array of items and pagination metadata.
        """
        params: Dict[str, Any] = {"scopePath": path, "recursionLevel": recursion_level}
        if branch:
            short = branch.replace("refs/heads/", "", 1)
            params["versionDescriptor.version"] = short
            params["versionDescriptor.versionType"] = "branch"
        try:
            log_debug(f"Listing items for {path} in {repository}")
            payload = self._request(
                "GET",
                f"/git/repositories/{quote(repository, safe='')}/items",
                project=project,
                params=params,
            )
            items = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            data = [self._serialize_item(i) for i in items]
            return json.dumps({"data": data, "meta": self._build_meta(1, len(data), len(data))}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while listing items: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while listing items")
            return self._json_error(str(e))

    async def alist_items(
        self,
        repository: str,
        path: str = "/",
        branch: Optional[str] = None,
        recursion_level: str = "oneLevel",
        project: Optional[str] = None,
    ) -> str:
        """List items under a repository path using async HTTP requests.

        Args:
            repository: Repository ID or name.
            path: Directory path inside the repository. Defaults to repo root.
            branch: Optional branch (with or without `refs/heads/` prefix). Defaults to the repo's default branch.
            recursion_level: One of `none`, `oneLevel`, `full`.
            project: Optional project name. Falls back to the toolkit's default project.

        Returns:
            JSON string with a `data` array of items and pagination metadata.
        """
        params: Dict[str, Any] = {"scopePath": path, "recursionLevel": recursion_level}
        if branch:
            short = branch.replace("refs/heads/", "", 1)
            params["versionDescriptor.version"] = short
            params["versionDescriptor.versionType"] = "branch"
        try:
            log_debug(f"Listing items for {path} in {repository}")
            payload = await self._arequest(
                "GET",
                f"/git/repositories/{quote(repository, safe='')}/items",
                project=project,
                params=params,
            )
            items = (payload or {}).get("value", []) if isinstance(payload, dict) else []
            data = [self._serialize_item(i) for i in items]
            return json.dumps({"data": data, "meta": self._build_meta(1, len(data), len(data))}, indent=2)
        except httpx.HTTPStatusError as e:
            message = self._http_error_message(e.response)
            log_error(f"Azure DevOps API error while listing items: {message}")
            return self._json_error(message)
        except Exception as e:
            logger.exception("Unexpected error while listing items")
            return self._json_error(str(e))
