import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    from azure.devops.connection import Connection  # type: ignore
    from azure.devops.exceptions import AzureDevOpsAuthenticationError, AzureDevOpsServiceError  # type: ignore
    from azure.devops.v7_0.build.models import Build, BuildDefinitionReference  # type: ignore
    from azure.devops.v7_0.git.models import (  # type: ignore
        GitPullRequest,
        GitPullRequestCommentThread,
        GitPullRequestSearchCriteria,
        GitRefUpdate,
        GitRepositoryCreateOptions,
    )
    from azure.devops.v7_0.work_item_tracking.models import (  # type: ignore
        CommentCreate,
        JsonPatchOperation,
        Wiql,
    )
    from msrest.authentication import BasicAuthentication
except ImportError:
    raise ImportError("`azure-devops` not installed. Please install using `pip install azure-devops`")


class AzureDevOpsTools(Toolkit):
    def __init__(
        self,
        organization_url: Optional[str] = None,
        personal_access_token: Optional[str] = None,
        project: Optional[str] = None,
        # Projects
        enable_list_projects: bool = True,
        enable_get_project: bool = True,
        # Repositories
        enable_list_repositories: bool = True,
        enable_get_repository: bool = True,
        enable_create_repository: bool = True,
        enable_delete_repository: bool = True,
        # Branches
        enable_list_branches: bool = True,
        enable_create_branch: bool = True,
        enable_delete_branch: bool = True,
        # Pull Requests
        enable_list_pull_requests: bool = True,
        enable_get_pull_request: bool = True,
        enable_create_pull_request: bool = True,
        enable_update_pull_request: bool = True,
        enable_complete_pull_request: bool = True,
        enable_abandon_pull_request: bool = True,
        enable_get_pull_request_changes: bool = True,
        enable_get_pull_request_commits: bool = True,
        enable_list_pr_comments: bool = True,
        enable_add_pr_comment: bool = True,
        enable_add_pr_reviewer: bool = True,
        # Commits
        enable_list_commits: bool = True,
        enable_get_commit: bool = True,
        enable_get_commit_changes: bool = True,
        # Work Items
        enable_list_work_items: bool = True,
        enable_get_work_item: bool = True,
        enable_create_work_item: bool = True,
        enable_update_work_item: bool = True,
        enable_delete_work_item: bool = True,
        enable_list_work_item_comments: bool = True,
        enable_add_work_item_comment: bool = True,
        # Pipelines / Builds
        enable_list_pipelines: bool = True,
        enable_trigger_pipeline: bool = True,
        enable_get_pipeline_runs: bool = True,
        enable_cancel_build: bool = True,
        enable_get_build_logs: bool = True,
        # Releases
        enable_list_release_definitions: bool = True,
        enable_list_releases: bool = True,
        enable_create_release: bool = True,
        # Teams
        enable_list_teams: bool = True,
        enable_get_team_members: bool = True,
        # Iterations / Sprints
        enable_list_iterations: bool = True,
        enable_get_iteration_work_items: bool = True,
        **kwargs,
    ):
        self.organization_url = (organization_url or getenv("AZURE_DEVOPS_ORG_URL") or "").rstrip("/")
        self.personal_access_token = personal_access_token or getenv("AZURE_DEVOPS_PAT")
        self.default_project = project or getenv("AZURE_DEVOPS_PROJECT")
        self._connection: Optional[Connection] = None

        tools: List[Any] = []

        if enable_list_projects:
            tools.append(self.list_projects)
        if enable_get_project:
            tools.append(self.get_project)
        if enable_list_repositories:
            tools.append(self.list_repositories)
        if enable_get_repository:
            tools.append(self.get_repository)
        if enable_create_repository:
            tools.append(self.create_repository)
        if enable_delete_repository:
            tools.append(self.delete_repository)
        if enable_list_branches:
            tools.append(self.list_branches)
        if enable_create_branch:
            tools.append(self.create_branch)
        if enable_delete_branch:
            tools.append(self.delete_branch)
        if enable_list_pull_requests:
            tools.append(self.list_pull_requests)
        if enable_get_pull_request:
            tools.append(self.get_pull_request)
        if enable_create_pull_request:
            tools.append(self.create_pull_request)
        if enable_update_pull_request:
            tools.append(self.update_pull_request)
        if enable_complete_pull_request:
            tools.append(self.complete_pull_request)
        if enable_abandon_pull_request:
            tools.append(self.abandon_pull_request)
        if enable_get_pull_request_changes:
            tools.append(self.get_pull_request_changes)
        if enable_get_pull_request_commits:
            tools.append(self.get_pull_request_commits)
        if enable_list_pr_comments:
            tools.append(self.list_pr_comments)
        if enable_add_pr_comment:
            tools.append(self.add_pr_comment)
        if enable_add_pr_reviewer:
            tools.append(self.add_pr_reviewer)
        if enable_list_commits:
            tools.append(self.list_commits)
        if enable_get_commit:
            tools.append(self.get_commit)
        if enable_get_commit_changes:
            tools.append(self.get_commit_changes)
        if enable_list_work_items:
            tools.append(self.list_work_items)
        if enable_get_work_item:
            tools.append(self.get_work_item)
        if enable_create_work_item:
            tools.append(self.create_work_item)
        if enable_update_work_item:
            tools.append(self.update_work_item)
        if enable_delete_work_item:
            tools.append(self.delete_work_item)
        if enable_list_work_item_comments:
            tools.append(self.list_work_item_comments)
        if enable_add_work_item_comment:
            tools.append(self.add_work_item_comment)
        if enable_list_pipelines:
            tools.append(self.list_pipelines)
        if enable_trigger_pipeline:
            tools.append(self.trigger_pipeline)
        if enable_get_pipeline_runs:
            tools.append(self.get_pipeline_runs)
        if enable_cancel_build:
            tools.append(self.cancel_build)
        if enable_get_build_logs:
            tools.append(self.get_build_logs)
        if enable_list_release_definitions:
            tools.append(self.list_release_definitions)
        if enable_list_releases:
            tools.append(self.list_releases)
        if enable_create_release:
            tools.append(self.create_release)
        if enable_list_teams:
            tools.append(self.list_teams)
        if enable_get_team_members:
            tools.append(self.get_team_members)
        if enable_list_iterations:
            tools.append(self.list_iterations)
        if enable_get_iteration_work_items:
            tools.append(self.get_iteration_work_items)

        super().__init__(name="azure_devops", tools=tools, **kwargs)

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                    #
    # ------------------------------------------------------------------ #

    def _get_connection(self) -> Connection:
        if self._connection is None:
            if not self.organization_url:
                raise ValueError("organization_url is required (or set AZURE_DEVOPS_ORG_URL env var)")
            if not self.personal_access_token:
                raise ValueError("personal_access_token is required (or set AZURE_DEVOPS_PAT env var)")
            credentials = BasicAuthentication("", self.personal_access_token)
            self._connection = Connection(base_url=self.organization_url, creds=credentials)
        return self._connection

    def _resolve_project(self, project: Optional[str]) -> str:
        resolved = project or self.default_project
        if not resolved:
            raise ValueError("project is required (pass it or set AZURE_DEVOPS_PROJECT env var)")
        return resolved

    @staticmethod
    def _bound_page_size(per_page: int, max_size: int = 100) -> int:
        return max(1, min(per_page, max_size))

    def _json_error(self, message: str) -> str:
        return json.dumps({"error": message})

    def _build_meta(self, page: int, per_page: int, returned_items: int) -> Dict[str, int]:
        return {"current_page": page, "per_page": per_page, "returned_items": returned_items}

    #  Serialisers
    @staticmethod
    def _serialize_project(project: Any) -> Dict[str, Any]:
        return {
            "id": project.id,
            "name": project.name,
            "description": getattr(project, "description", None),
            "state": str(project.state) if project.state else None,
            "visibility": str(project.visibility) if project.visibility else None,
            "last_update_time": project.last_update_time.isoformat()
            if getattr(project, "last_update_time", None)
            else None,
            "url": getattr(project, "url", None),
        }

    @staticmethod
    def _serialize_repository(repo: Any) -> Dict[str, Any]:
        return {
            "id": repo.id,
            "name": repo.name,
            "default_branch": getattr(repo, "default_branch", None),
            "remote_url": getattr(repo, "remote_url", None),
            "web_url": getattr(repo, "web_url", None),
            "size": getattr(repo, "size", None),
            "project": repo.project.name if getattr(repo, "project", None) else None,
        }

    @staticmethod
    def _serialize_branch(ref: Any) -> Dict[str, Any]:
        name = ref.name.replace("refs/heads/", "") if ref.name else ref.name
        return {
            "name": name,
            "full_name": ref.name,
            "object_id": getattr(ref, "object_id", None),
            "creator": ref.creator.display_name if getattr(ref, "creator", None) else None,
            "url": getattr(ref, "url", None),
        }

    @staticmethod
    def _serialize_pull_request(pr: Any) -> Dict[str, Any]:
        return {
            "pull_request_id": pr.pull_request_id,
            "title": pr.title,
            "description": getattr(pr, "description", None),
            "status": str(pr.status) if pr.status else None,
            "source_branch": pr.source_ref_name,
            "target_branch": pr.target_ref_name,
            "created_by": pr.created_by.display_name if getattr(pr, "created_by", None) else None,
            "creation_date": pr.creation_date.isoformat() if getattr(pr, "creation_date", None) else None,
            "closed_date": pr.closed_date.isoformat() if getattr(pr, "closed_date", None) else None,
            "url": getattr(pr, "url", None),
            "merge_status": str(pr.merge_status) if getattr(pr, "merge_status", None) else None,
            "is_draft": getattr(pr, "is_draft", False),
            "reviewers": [
                {"display_name": r.display_name, "vote": r.vote} for r in (getattr(pr, "reviewers", None) or [])
            ],
        }

    @staticmethod
    def _serialize_commit(commit: Any) -> Dict[str, Any]:
        return {
            "commit_id": commit.commit_id,
            "comment": getattr(commit, "comment", None),
            "author": {
                "name": commit.author.name if getattr(commit, "author", None) else None,
                "email": commit.author.email if getattr(commit, "author", None) else None,
                "date": commit.author.date.isoformat()
                if getattr(commit, "author", None) and commit.author.date
                else None,
            },
            "url": getattr(commit, "url", None),
            "remote_url": getattr(commit, "remote_url", None),
        }

    @staticmethod
    def _serialize_work_item(wi: Any) -> Dict[str, Any]:
        fields = wi.fields or {}
        return {
            "id": wi.id,
            "url": wi.url,
            "title": fields.get("System.Title"),
            "state": fields.get("System.State"),
            "type": fields.get("System.WorkItemType"),
            "assigned_to": (
                fields["System.AssignedTo"].get("displayName")
                if isinstance(fields.get("System.AssignedTo"), dict)
                else fields.get("System.AssignedTo")
            ),
            "area_path": fields.get("System.AreaPath"),
            "iteration_path": fields.get("System.IterationPath"),
            "created_date": fields.get("System.CreatedDate"),
            "changed_date": fields.get("System.ChangedDate"),
            "description": fields.get("System.Description"),
            "priority": fields.get("Microsoft.VSTS.Common.Priority"),
            "tags": fields.get("System.Tags"),
        }

    @staticmethod
    def _serialize_pipeline(pipeline: Any) -> Dict[str, Any]:
        return {
            "id": pipeline.id,
            "name": pipeline.name,
            "folder": getattr(pipeline, "folder", None),
            "revision": getattr(pipeline, "revision", None),
            "url": getattr(pipeline, "url", None),
        }

    @staticmethod
    def _serialize_build(build: Any) -> Dict[str, Any]:
        return {
            "id": build.id,
            "build_number": build.build_number,
            "status": str(build.status) if build.status else None,
            "result": str(build.result) if getattr(build, "result", None) else None,
            "source_branch": getattr(build, "source_branch", None),
            "source_version": getattr(build, "source_version", None),
            "queue_time": build.queue_time.isoformat() if getattr(build, "queue_time", None) else None,
            "start_time": build.start_time.isoformat() if getattr(build, "start_time", None) else None,
            "finish_time": build.finish_time.isoformat() if getattr(build, "finish_time", None) else None,
            "requested_by": build.requested_by.display_name if getattr(build, "requested_by", None) else None,
            "url": getattr(build, "url", None),
        }

    @staticmethod
    def _serialize_release_definition(rd: Any) -> Dict[str, Any]:
        return {
            "id": rd.id,
            "name": rd.name,
            "path": getattr(rd, "path", None),
            "url": getattr(rd, "url", None),
            "created_by": rd.created_by.display_name if getattr(rd, "created_by", None) else None,
            "created_on": rd.created_on.isoformat() if getattr(rd, "created_on", None) else None,
            "modified_on": rd.modified_on.isoformat() if getattr(rd, "modified_on", None) else None,
        }

    @staticmethod
    def _serialize_release(release: Any) -> Dict[str, Any]:
        return {
            "id": release.id,
            "name": release.name,
            "status": str(release.status) if release.status else None,
            "created_by": release.created_by.display_name if getattr(release, "created_by", None) else None,
            "created_on": release.created_on.isoformat() if getattr(release, "created_on", None) else None,
            "modified_on": release.modified_on.isoformat() if getattr(release, "modified_on", None) else None,
            "url": getattr(release, "url", None),
            "release_definition": release.release_definition.name
            if getattr(release, "release_definition", None)
            else None,
        }

    @staticmethod
    def _serialize_team(team: Any) -> Dict[str, Any]:
        return {
            "id": team.id,
            "name": team.name,
            "description": getattr(team, "description", None),
            "url": getattr(team, "url", None),
            "project_name": getattr(team, "project_name", None),
        }

    @staticmethod
    def _serialize_team_member(member: Any) -> Dict[str, Any]:
        identity = getattr(member, "identity", member)
        return {
            "id": getattr(identity, "id", None),
            "display_name": getattr(identity, "display_name", None),
            "unique_name": getattr(identity, "unique_name", None),
            "url": getattr(identity, "url", None),
            "is_team_admin": getattr(member, "is_team_admin", False),
        }

    @staticmethod
    def _serialize_iteration(iteration: Any) -> Dict[str, Any]:
        attrs = getattr(iteration, "attributes", None)
        return {
            "id": iteration.id,
            "name": iteration.name,
            "path": getattr(iteration, "path", None),
            "url": getattr(iteration, "url", None),
            "start_date": attrs.start_date.isoformat() if attrs and getattr(attrs, "start_date", None) else None,
            "finish_date": attrs.finish_date.isoformat() if attrs and getattr(attrs, "finish_date", None) else None,
            "time_frame": str(attrs.time_frame) if attrs and getattr(attrs, "time_frame", None) else None,
        }

    #  PROJECTS
    def list_projects(self, page: int = 1, per_page: int = 20) -> str:
        """
        List all projects in the Azure DevOps organization.

        Args:
            page: Page number for pagination (1-based).
            per_page: Number of items per page (max 100).

        Returns:
            JSON string containing project data and pagination metadata.
        """
        try:
            per_page = self._bound_page_size(per_page)
            conn = self._get_connection()
            core_client = conn.clients.get_core_client()
            log_debug("Listing Azure DevOps projects")
            all_projects = list(core_client.get_projects())
            start = (page - 1) * per_page
            page_items = all_projects[start : start + per_page]
            data = [self._serialize_project(p) for p in page_items]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error listing projects: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error listing projects")
            return self._json_error(str(e))

    def get_project(self, project: Optional[str] = None) -> str:
        """
        Get details for a single Azure DevOps project.

        Args:
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing project details.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            core_client = conn.clients.get_core_client()
            log_debug(f"Getting project: {project}")
            proj = core_client.get_project(project)
            return json.dumps(self._serialize_project(proj), indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error getting project {project}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error getting project {project}")
            return self._json_error(str(e))

    #  REPOSITORIES

    def list_repositories(self, project: Optional[str] = None) -> str:
        """
        List all Git repositories in a project.

        Args:
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing a list of repositories.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            log_debug(f"Listing repositories for project: {project}")
            repos = git_client.get_repositories(project=project)
            data = [self._serialize_repository(r) for r in repos]
            return json.dumps({"data": data, "meta": {"returned_items": len(data)}}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error listing repositories: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error listing repositories")
            return self._json_error(str(e))

    def get_repository(self, repository_id_or_name: str, project: Optional[str] = None) -> str:
        """
        Get details for a single Git repository.

        Args:
            repository_id_or_name: Repository ID (GUID) or name.
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing repository details.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            log_debug(f"Getting repository: {repository_id_or_name}")
            repo = git_client.get_repository(repository_id=repository_id_or_name, project=project)
            return json.dumps(self._serialize_repository(repo), indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error getting repository {repository_id_or_name}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error getting repository {repository_id_or_name}")
            return self._json_error(str(e))

    def create_repository(self, name: str, project: Optional[str] = None) -> str:
        """
        Create a new Git repository in a project.

        Args:
            name: Name of the new repository.
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing the created repository details.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            core_client = conn.clients.get_core_client()
            proj = core_client.get_project(project)
            git_repo_options = GitRepositoryCreateOptions(name=name, project=proj)
            log_debug(f"Creating repository '{name}' in project: {project}")
            repo = git_client.create_repository(git_repository_to_create=git_repo_options, project=project)
            return json.dumps(self._serialize_repository(repo), indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error creating repository: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error creating repository")
            return self._json_error(str(e))

    def delete_repository(self, repository_id: str, project: Optional[str] = None) -> str:
        """
        Delete a Git repository.

        Args:
            repository_id: Repository ID (GUID) or name.
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string confirming deletion.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            repo = git_client.get_repository(repository_id=repository_id, project=project)
            log_debug(f"Deleting repository: {repository_id}")
            git_client.delete_repository(repository_id=repo.id, project=project)
            return json.dumps({"message": f"Repository '{repository_id}' deleted successfully."}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error deleting repository {repository_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error deleting repository {repository_id}")
            return self._json_error(str(e))

    #  BRANCHES

    def list_branches(
        self,
        repository_id: str,
        project: Optional[str] = None,
        filter_contains: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> str:
        """
        List branches in a Git repository.

        Args:
            repository_id: Repository ID or name.
            project: Project name or ID. Defaults to the toolkit's configured project.
            filter_contains: Optional substring to filter branch names.
            page: Page number for pagination (1-based).
            per_page: Number of items per page (max 100).

        Returns:
            JSON string containing branch data and pagination metadata.
        """
        try:
            per_page = self._bound_page_size(per_page)
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            log_debug(f"Listing branches for repository: {repository_id}")
            refs = git_client.get_refs(
                repository_id=repository_id,
                project=project,
                filter="heads/",
                filter_contains=filter_contains,
            )
            all_refs = list(refs)
            start = (page - 1) * per_page
            page_items = all_refs[start : start + per_page]
            data = [self._serialize_branch(r) for r in page_items]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error listing branches: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error listing branches")
            return self._json_error(str(e))

    def create_branch(
        self,
        repository_id: str,
        branch_name: str,
        source_branch: str,
        project: Optional[str] = None,
    ) -> str:
        """
        Create a new branch from an existing branch.

        Args:
            repository_id: Repository ID or name.
            branch_name: Name of the new branch (without 'refs/heads/' prefix).
            source_branch: Source branch to create from (without 'refs/heads/' prefix).
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing the created branch details.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            refs = list(
                git_client.get_refs(repository_id=repository_id, project=project, filter=f"heads/{source_branch}")
            )
            if not refs:
                return self._json_error(f"Source branch '{source_branch}' not found.")
            source_object_id = refs[0].object_id
            new_ref = GitRefUpdate(
                name=f"refs/heads/{branch_name}",
                old_object_id="0000000000000000000000000000000000000000",
                new_object_id=source_object_id,
            )
            log_debug(f"Creating branch '{branch_name}' from '{source_branch}' in repo: {repository_id}")
            result = git_client.update_refs(ref_updates=[new_ref], repository_id=repository_id, project=project)
            if result and result[0].success:
                return json.dumps(
                    {
                        "name": branch_name,
                        "full_name": f"refs/heads/{branch_name}",
                        "object_id": source_object_id,
                        "message": f"Branch '{branch_name}' created successfully.",
                    },
                    indent=2,
                )
            return self._json_error(f"Failed to create branch '{branch_name}'.")
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error creating branch: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error creating branch")
            return self._json_error(str(e))

    def delete_branch(
        self,
        repository_id: str,
        branch_name: str,
        project: Optional[str] = None,
    ) -> str:
        """
        Delete a branch from a Git repository.

        Args:
            repository_id: Repository ID or name.
            branch_name: Branch name to delete (without 'refs/heads/' prefix).
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string confirming deletion.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            refs = list(
                git_client.get_refs(repository_id=repository_id, project=project, filter=f"heads/{branch_name}")
            )
            if not refs:
                return self._json_error(f"Branch '{branch_name}' not found.")
            object_id = refs[0].object_id
            delete_ref = GitRefUpdate(
                name=f"refs/heads/{branch_name}",
                old_object_id=object_id,
                new_object_id="0000000000000000000000000000000000000000",
            )
            log_debug(f"Deleting branch '{branch_name}' from repository: {repository_id}")
            result = git_client.update_refs(ref_updates=[delete_ref], repository_id=repository_id, project=project)
            if result and result[0].success:
                return json.dumps({"message": f"Branch '{branch_name}' deleted successfully."}, indent=2)
            return self._json_error(f"Failed to delete branch '{branch_name}'.")
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error deleting branch: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error deleting branch")
            return self._json_error(str(e))

    #  PULL REQUESTS

    def list_pull_requests(
        self,
        repository_id: str,
        project: Optional[str] = None,
        status: str = "active",
        source_branch: Optional[str] = None,
        target_branch: Optional[str] = None,
        creator_id: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> str:
        """
        List pull requests for a repository.

        Args:
            repository_id: Repository ID or name.
            project: Project name or ID. Defaults to the toolkit's configured project.
            status: PR status - 'active', 'completed', 'abandoned', or 'all'.
            source_branch: Optional source branch filter (e.g. 'refs/heads/feature/x').
            target_branch: Optional target branch filter (e.g. 'refs/heads/main').
            creator_id: Optional creator identity ID filter.
            page: Page number for pagination (1-based).
            per_page: Number of items per page (max 100).

        Returns:
            JSON string containing pull request data and pagination metadata.
        """
        try:
            per_page = self._bound_page_size(per_page)
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            search_criteria = GitPullRequestSearchCriteria(
                status=status,
                source_ref_name=source_branch,
                target_ref_name=target_branch,
                creator_id=creator_id,
            )
            skip = (page - 1) * per_page
            log_debug(f"Listing pull requests for repository: {repository_id}")
            prs = git_client.get_pull_requests(
                repository_id=repository_id,
                search_criteria=search_criteria,
                project=project,
                skip=skip,
                top=per_page,
            )
            data = [self._serialize_pull_request(pr) for pr in prs]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error listing pull requests: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error listing pull requests")
            return self._json_error(str(e))

    def get_pull_request(
        self,
        pull_request_id: int,
        repository_id: str,
        project: Optional[str] = None,
    ) -> str:
        """
        Get details for a single pull request.

        Args:
            pull_request_id: The numeric ID of the pull request.
            repository_id: Repository ID or name.
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing pull request details.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            log_debug(f"Getting pull request: {pull_request_id}")
            pr = git_client.get_pull_request(
                repository_id=repository_id,
                pull_request_id=pull_request_id,
                project=project,
            )
            return json.dumps(self._serialize_pull_request(pr), indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error getting PR {pull_request_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error getting PR {pull_request_id}")
            return self._json_error(str(e))

    def create_pull_request(
        self,
        repository_id: str,
        title: str,
        source_branch: str,
        target_branch: str,
        description: Optional[str] = None,
        project: Optional[str] = None,
        is_draft: bool = False,
    ) -> str:
        """
        Create a new pull request.

        Args:
            repository_id: Repository ID or name.
            title: Title of the pull request.
            source_branch: Source branch (e.g. 'refs/heads/feature/my-branch').
            target_branch: Target branch (e.g. 'refs/heads/main').
            description: Optional body text.
            project: Project name or ID. Defaults to the toolkit's configured project.
            is_draft: Whether to create as a draft PR.

        Returns:
            JSON string containing the created pull request details.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            pr = GitPullRequest(
                title=title,
                description=description,
                source_ref_name=source_branch,
                target_ref_name=target_branch,
                is_draft=is_draft,
            )
            log_debug(f"Creating pull request in repository: {repository_id}")
            created_pr = git_client.create_pull_request(
                git_pull_request_to_create=pr,
                repository_id=repository_id,
                project=project,
            )
            return json.dumps(self._serialize_pull_request(created_pr), indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error creating pull request: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error creating pull request")
            return self._json_error(str(e))

    def update_pull_request(
        self,
        pull_request_id: int,
        repository_id: str,
        project: Optional[str] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        target_branch: Optional[str] = None,
        is_draft: Optional[bool] = None,
    ) -> str:
        """
        Update an existing pull request's metadata.

        Args:
            pull_request_id: The numeric ID of the pull request.
            repository_id: Repository ID or name.
            project: Project name or ID. Defaults to the toolkit's configured project.
            title: New title for the PR.
            description: New description for the PR.
            target_branch: New target branch (e.g. 'refs/heads/main').
            is_draft: Change draft status.

        Returns:
            JSON string containing the updated pull request details.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            update = GitPullRequest(
                title=title,
                description=description,
                target_ref_name=target_branch,
                is_draft=is_draft,
            )
            log_debug(f"Updating pull request: {pull_request_id}")
            updated_pr = git_client.update_pull_request(
                git_pull_request_to_update=update,
                repository_id=repository_id,
                pull_request_id=pull_request_id,
                project=project,
            )
            return json.dumps(self._serialize_pull_request(updated_pr), indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error updating PR {pull_request_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error updating PR {pull_request_id}")
            return self._json_error(str(e))

    def complete_pull_request(
        self,
        pull_request_id: int,
        repository_id: str,
        project: Optional[str] = None,
        delete_source_branch: bool = False,
    ) -> str:
        """
        Complete (merge) a pull request.

        Args:
            pull_request_id: The numeric ID of the pull request.
            repository_id: Repository ID or name.
            project: Project name or ID. Defaults to the toolkit's configured project.
            delete_source_branch: Whether to delete the source branch after merging.

        Returns:
            JSON string containing the completed pull request details.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            pr = git_client.get_pull_request(
                repository_id=repository_id,
                pull_request_id=pull_request_id,
                project=project,
            )
            update = GitPullRequest(
                status="completed",
                last_merge_source_commit=pr.last_merge_source_commit,
                completion_options={"deleteSourceBranch": delete_source_branch},
            )
            log_debug(f"Completing pull request: {pull_request_id}")
            completed_pr = git_client.update_pull_request(
                git_pull_request_to_update=update,
                repository_id=repository_id,
                pull_request_id=pull_request_id,
                project=project,
            )
            return json.dumps(self._serialize_pull_request(completed_pr), indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error completing PR {pull_request_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error completing PR {pull_request_id}")
            return self._json_error(str(e))

    def abandon_pull_request(
        self,
        pull_request_id: int,
        repository_id: str,
        project: Optional[str] = None,
    ) -> str:
        """
        Abandon (close without merging) a pull request.

        Args:
            pull_request_id: The numeric ID of the pull request.
            repository_id: Repository ID or name.
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing the abandoned pull request details.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            update = GitPullRequest(status="abandoned")
            log_debug(f"Abandoning pull request: {pull_request_id}")
            abandoned_pr = git_client.update_pull_request(
                git_pull_request_to_update=update,
                repository_id=repository_id,
                pull_request_id=pull_request_id,
                project=project,
            )
            return json.dumps(self._serialize_pull_request(abandoned_pr), indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error abandoning PR {pull_request_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error abandoning PR {pull_request_id}")
            return self._json_error(str(e))

    def get_pull_request_changes(
        self,
        pull_request_id: int,
        repository_id: str,
        project: Optional[str] = None,
    ) -> str:
        """
        Get file changes (diff) for a pull request.

        Args:
            pull_request_id: The numeric ID of the pull request.
            repository_id: Repository ID or name.
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing the list of changed files.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            log_debug(f"Getting changes for PR: {pull_request_id}")
            iterations = git_client.get_pull_request_iterations(
                repository_id=repository_id,
                pull_request_id=pull_request_id,
                project=project,
            )
            if not iterations:
                return json.dumps({"data": [], "message": "No iterations found."}, indent=2)
            latest_iteration_id = iterations[-1].id
            changes = git_client.get_pull_request_iteration_changes(
                repository_id=repository_id,
                pull_request_id=pull_request_id,
                iteration_id=latest_iteration_id,
                project=project,
            )
            data = []
            for change in changes.change_entries or []:
                ct = getattr(change, "change_type", None) or getattr(change, "changeType", None)
                item = getattr(change, "item", None)
                data.append(
                    {
                        "change_type": str(ct) if ct else None,
                        "path": item.path if item else None,
                        "url": item.url if item else None,
                    }
                )
            return json.dumps({"data": data, "meta": {"returned_items": len(data)}}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error getting PR changes {pull_request_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error getting PR changes {pull_request_id}")
            return self._json_error(str(e))

    def get_pull_request_commits(
        self,
        pull_request_id: int,
        repository_id: str,
        project: Optional[str] = None,
    ) -> str:
        """
        Get the list of commits in a pull request.

        Args:
            pull_request_id: The numeric ID of the pull request.
            repository_id: Repository ID or name.
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing the list of commits.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            log_debug(f"Getting commits for PR: {pull_request_id}")
            commits = git_client.get_pull_request_commits(
                repository_id=repository_id,
                pull_request_id=pull_request_id,
                project=project,
            )
            data = [self._serialize_commit(c) for c in commits]
            return json.dumps({"data": data, "meta": {"returned_items": len(data)}}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error getting PR commits {pull_request_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error getting PR commits {pull_request_id}")
            return self._json_error(str(e))

    def list_pr_comments(
        self,
        pull_request_id: int,
        repository_id: str,
        project: Optional[str] = None,
    ) -> str:
        """
        List all comment threads on a pull request.

        Args:
            pull_request_id: The numeric ID of the pull request.
            repository_id: Repository ID or name.
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing comment threads.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            log_debug(f"Listing comments for PR: {pull_request_id}")
            threads = git_client.get_threads(
                repository_id=repository_id,
                pull_request_id=pull_request_id,
                project=project,
            )
            data = []
            for thread in threads:
                comments = [
                    {
                        "id": c.id,
                        "content": c.content,
                        "author": c.author.display_name if getattr(c, "author", None) else None,
                        "published_date": c.published_date.isoformat() if getattr(c, "published_date", None) else None,
                        "comment_type": str(c.comment_type) if getattr(c, "comment_type", None) else None,
                    }
                    for c in (thread.comments or [])
                ]
                data.append(
                    {
                        "thread_id": thread.id,
                        "status": str(thread.status) if thread.status else None,
                        "is_deleted": getattr(thread, "is_deleted", False),
                        "comments": comments,
                    }
                )
            return json.dumps({"data": data, "meta": {"returned_items": len(data)}}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error listing PR comments: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error listing PR comments")
            return self._json_error(str(e))

    def add_pr_comment(
        self,
        pull_request_id: int,
        repository_id: str,
        comment: str,
        project: Optional[str] = None,
    ) -> str:
        """
        Add a top-level comment to a pull request.

        Args:
            pull_request_id: The numeric ID of the pull request.
            repository_id: Repository ID or name.
            comment: The comment text.
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string confirming the comment was added.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            from azure.devops.v7_0.git.models import Comment as GitComment

            thread = GitPullRequestCommentThread(
                comments=[GitComment(content=comment, comment_type=1)],
                status=1,
            )
            log_debug(f"Adding comment to PR: {pull_request_id}")
            created_thread = git_client.create_thread(
                comment_thread=thread,
                repository_id=repository_id,
                pull_request_id=pull_request_id,
                project=project,
            )
            first_comment = created_thread.comments[0] if created_thread.comments else None
            return json.dumps(
                {
                    "thread_id": created_thread.id,
                    "comment_id": first_comment.id if first_comment else None,
                    "content": first_comment.content if first_comment else None,
                    "message": "Comment added successfully.",
                },
                indent=2,
            )
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error adding PR comment: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error adding PR comment")
            return self._json_error(str(e))

    def add_pr_reviewer(
        self,
        pull_request_id: int,
        repository_id: str,
        reviewer_id: str,
        project: Optional[str] = None,
        is_required: bool = False,
    ) -> str:
        """
        Add a reviewer to a pull request.

        Args:
            pull_request_id: The numeric ID of the pull request.
            repository_id: Repository ID or name.
            reviewer_id: The identity ID (GUID) of the reviewer to add.
            project: Project name or ID. Defaults to the toolkit's configured project.
            is_required: Whether the reviewer is required.

        Returns:
            JSON string confirming the reviewer was added.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            from azure.devops.v7_0.git.models import IdentityRefWithVote

            reviewer = IdentityRefWithVote(id=reviewer_id, is_required=is_required)
            log_debug(f"Adding reviewer {reviewer_id} to PR: {pull_request_id}")
            result = git_client.create_pull_request_reviewer(
                reviewer=reviewer,
                repository_id=repository_id,
                pull_request_id=pull_request_id,
                reviewer_id=reviewer_id,
                project=project,
            )
            return json.dumps(
                {
                    "reviewer_id": reviewer_id,
                    "display_name": getattr(result, "display_name", None),
                    "is_required": getattr(result, "is_required", None),
                    "vote": getattr(result, "vote", None),
                    "message": "Reviewer added successfully.",
                },
                indent=2,
            )
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error adding PR reviewer: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error adding PR reviewer")
            return self._json_error(str(e))

    #  COMMITS

    def list_commits(
        self,
        repository_id: str,
        project: Optional[str] = None,
        branch: Optional[str] = None,
        author: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> str:
        """
        List commits in a Git repository.

        Args:
            repository_id: Repository ID or name.
            project: Project name or ID. Defaults to the toolkit's configured project.
            branch: Optional branch name to filter commits (e.g. 'main').
            author: Optional author name/email filter.
            from_date: Optional start date filter (ISO 8601 format).
            to_date: Optional end date filter (ISO 8601 format).
            page: Page number for pagination (1-based).
            per_page: Number of items per page (max 100).

        Returns:
            JSON string containing commit data and pagination metadata.
        """
        try:
            per_page = self._bound_page_size(per_page)
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            from azure.devops.v7_0.git.models import GitQueryCommitsCriteria

            criteria = GitQueryCommitsCriteria(
                item_version={"version": branch, "versionType": "branch"} if branch else None,
                author=author,
                from_date=from_date,
                to_date=to_date,
                skip=(page - 1) * per_page,
                top=per_page,
            )
            log_debug(f"Listing commits for repository: {repository_id}")
            commits = git_client.get_commits_batch(
                search_criteria=criteria,
                repository_id=repository_id,
                project=project,
            )
            data = [self._serialize_commit(c) for c in commits]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error listing commits: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error listing commits")
            return self._json_error(str(e))

    def get_commit(
        self,
        commit_id: str,
        repository_id: str,
        project: Optional[str] = None,
    ) -> str:
        """
        Get details for a single commit.

        Args:
            commit_id: The SHA of the commit.
            repository_id: Repository ID or name.
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing commit details.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            log_debug(f"Getting commit: {commit_id}")
            commit = git_client.get_commit(
                commit_id=commit_id,
                repository_id=repository_id,
                project=project,
            )
            return json.dumps(self._serialize_commit(commit), indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error getting commit {commit_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error getting commit {commit_id}")
            return self._json_error(str(e))

    def get_commit_changes(
        self,
        commit_id: str,
        repository_id: str,
        project: Optional[str] = None,
    ) -> str:
        """
        Get files changed in a commit.

        Args:
            commit_id: The SHA of the commit.
            repository_id: Repository ID or name.
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing the list of changed files.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            git_client = conn.clients.get_git_client()
            log_debug(f"Getting changes for commit: {commit_id}")
            changes = git_client.get_changes(
                commit_id=commit_id,
                repository_id=repository_id,
                project=project,
            )
            data = []
            for change in changes.changes or []:
                item = getattr(change, "item", None)
                if isinstance(change, dict):
                    change_type = change.get("changeType") or change.get("change_type")
                    item_raw = change.get("item", {})
                    data.append(
                        {
                            "change_type": str(change_type) if change_type else None,
                            "path": item_raw.get("path")
                            if isinstance(item_raw, dict)
                            else getattr(item_raw, "path", None),
                            "url": item_raw.get("url")
                            if isinstance(item_raw, dict)
                            else getattr(item_raw, "url", None),
                            "object_type": None,
                        }
                    )
                else:
                    item = getattr(change, "item", None)
                    data.append(
                        {
                            "change_type": str(change.change_type) if getattr(change, "change_type", None) else None,
                            "path": item.path if item else None,
                            "url": item.url if item else None,
                            "object_type": item.git_object_type if item else None,
                        }
                    )
            return json.dumps({"data": data, "meta": {"returned_items": len(data)}}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error getting commit changes {commit_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error getting commit changes {commit_id}")
            return self._json_error(str(e))

    #  WORK ITEMS

    def list_work_items(
        self,
        wiql_query: Optional[str] = None,
        project: Optional[str] = None,
        work_item_type: Optional[str] = None,
        state: Optional[str] = None,
        assigned_to: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> str:
        """
        List work items using WIQL (Work Item Query Language).

        Args:
            wiql_query: Optional raw WIQL query string. When provided, other filters are ignored.
            project: Project name or ID. Defaults to the toolkit's configured project.
            work_item_type: Filter by type, e.g. 'Bug', 'Task', 'User Story'.
            state: Filter by state, e.g. 'Active', 'Closed', 'New'.
            assigned_to: Filter by assignee display name or email.
            page: Page number for pagination (1-based).
            per_page: Number of items per page (max 100).

        Returns:
            JSON string containing work item data and pagination metadata.
        """
        try:
            per_page = self._bound_page_size(per_page)
            project = self._resolve_project(project)
            conn = self._get_connection()
            wit_client = conn.clients.get_work_item_tracking_client()

            if not wiql_query:
                conditions = ["[System.TeamProject] = @project"]
                if work_item_type:
                    conditions.append(f"[System.WorkItemType] = '{work_item_type}'")
                if state:
                    conditions.append(f"[System.State] = '{state}'")
                if assigned_to:
                    conditions.append(f"[System.AssignedTo] = '{assigned_to}'")
                wiql_query = (
                    "SELECT [System.Id] FROM WorkItems WHERE "
                    + " AND ".join(conditions)
                    + " ORDER BY [System.ChangedDate] DESC"
                )

            wiql = Wiql(query=wiql_query)
            log_debug(f"Running WIQL for project: {project}")
            from azure.devops.v7_0.work_item_tracking.models import TeamContext

            team_context = TeamContext(project=project)
            query_result = wit_client.query_by_wiql(wiql, team_context=team_context)
            all_ids = [wi.id for wi in (query_result.work_items or [])]
            start = (page - 1) * per_page
            page_ids = all_ids[start : start + per_page]

            if not page_ids:
                return json.dumps({"data": [], "meta": self._build_meta(page, per_page, 0)}, indent=2)

            work_items = wit_client.get_work_items(ids=page_ids, error_policy="omit")
            data = [self._serialize_work_item(wi) for wi in work_items if wi is not None]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error listing work items: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error listing work items")
            return self._json_error(str(e))

    def get_work_item(self, work_item_id: int, project: Optional[str] = None) -> str:
        """
        Get details for a single work item.

        Args:
            work_item_id: The numeric ID of the work item.
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing work item details.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            wit_client = conn.clients.get_work_item_tracking_client()
            log_debug(f"Getting work item: {work_item_id}")
            wi = wit_client.get_work_item(id=work_item_id)
            return json.dumps(self._serialize_work_item(wi), indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error getting work item {work_item_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error getting work item {work_item_id}")
            return self._json_error(str(e))

    def create_work_item(
        self,
        title: str,
        work_item_type: str = "Task",
        description: Optional[str] = None,
        assigned_to: Optional[str] = None,
        area_path: Optional[str] = None,
        iteration_path: Optional[str] = None,
        priority: Optional[int] = None,
        tags: Optional[str] = None,
        project: Optional[str] = None,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create a new work item.

        Args:
            title: Title of the work item.
            work_item_type: Type, e.g. 'Bug', 'Task', 'User Story'. Defaults to 'Task'.
            description: Optional description / body text.
            assigned_to: Optional assignee display name or email.
            area_path: Optional area path override.
            iteration_path: Optional iteration path override.
            priority: Optional priority value (1-4).
            tags: Optional semicolon-separated tags string.
            project: Project name or ID. Defaults to the toolkit's configured project.
            extra_fields: Optional dict of additional field path → value pairs.

        Returns:
            JSON string containing the created work item details.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            wit_client = conn.clients.get_work_item_tracking_client()

            patch_ops: List[JsonPatchOperation] = [
                JsonPatchOperation(op="add", path="/fields/System.Title", value=title),
            ]
            if description:
                patch_ops.append(JsonPatchOperation(op="add", path="/fields/System.Description", value=description))
            if assigned_to:
                patch_ops.append(JsonPatchOperation(op="add", path="/fields/System.AssignedTo", value=assigned_to))
            if area_path:
                patch_ops.append(JsonPatchOperation(op="add", path="/fields/System.AreaPath", value=area_path))
            if iteration_path:
                patch_ops.append(
                    JsonPatchOperation(op="add", path="/fields/System.IterationPath", value=iteration_path)
                )
            if priority is not None:
                patch_ops.append(
                    JsonPatchOperation(op="add", path="/fields/Microsoft.VSTS.Common.Priority", value=priority)
                )
            if tags:
                patch_ops.append(JsonPatchOperation(op="add", path="/fields/System.Tags", value=tags))
            for field_path, value in (extra_fields or {}).items():
                patch_ops.append(JsonPatchOperation(op="add", path=f"/fields/{field_path}", value=value))

            log_debug(f"Creating {work_item_type} in project: {project}")
            wi = wit_client.create_work_item(document=patch_ops, project=project, type=work_item_type)
            return json.dumps(self._serialize_work_item(wi), indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error creating work item: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error creating work item")
            return self._json_error(str(e))

    def update_work_item(
        self,
        work_item_id: int,
        title: Optional[str] = None,
        state: Optional[str] = None,
        description: Optional[str] = None,
        assigned_to: Optional[str] = None,
        priority: Optional[int] = None,
        tags: Optional[str] = None,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Update fields on an existing work item.

        Args:
            work_item_id: The numeric ID of the work item to update.
            title: New title.
            state: New state, e.g. 'Active', 'Closed', 'Resolved'.
            description: New description / body text.
            assigned_to: New assignee display name or email.
            priority: New priority value (1-4).
            tags: New semicolon-separated tags string.
            extra_fields: Additional field path → value pairs to update.

        Returns:
            JSON string containing the updated work item details.
        """
        try:
            conn = self._get_connection()
            wit_client = conn.clients.get_work_item_tracking_client()

            patch_ops: List[JsonPatchOperation] = []
            if title:
                patch_ops.append(JsonPatchOperation(op="add", path="/fields/System.Title", value=title))
            if state:
                patch_ops.append(JsonPatchOperation(op="add", path="/fields/System.State", value=state))
            if description:
                patch_ops.append(JsonPatchOperation(op="add", path="/fields/System.Description", value=description))
            if assigned_to:
                patch_ops.append(JsonPatchOperation(op="add", path="/fields/System.AssignedTo", value=assigned_to))
            if priority is not None:
                patch_ops.append(
                    JsonPatchOperation(op="add", path="/fields/Microsoft.VSTS.Common.Priority", value=priority)
                )
            if tags:
                patch_ops.append(JsonPatchOperation(op="add", path="/fields/System.Tags", value=tags))
            for field_path, value in (extra_fields or {}).items():
                patch_ops.append(JsonPatchOperation(op="add", path=f"/fields/{field_path}", value=value))

            if not patch_ops:
                return self._json_error("No fields provided to update.")

            log_debug(f"Updating work item: {work_item_id}")
            wi = wit_client.update_work_item(document=patch_ops, id=work_item_id)
            return json.dumps(self._serialize_work_item(wi), indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error updating work item {work_item_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error updating work item {work_item_id}")
            return self._json_error(str(e))

    def delete_work_item(
        self,
        work_item_id: int,
        project: Optional[str] = None,
        destroy: bool = False,
    ) -> str:
        """
        Delete a work item (moves to recycle bin, or permanently if destroy=True).

        Args:
            work_item_id: The numeric ID of the work item to delete.
            project: Project name or ID. Defaults to the toolkit's configured project.
            destroy: If True, permanently destroys the work item (cannot be undone).

        Returns:
            JSON string confirming deletion.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            wit_client = conn.clients.get_work_item_tracking_client()
            log_debug(f"Deleting work item: {work_item_id}")
            wit_client.delete_work_item(id=work_item_id, project=project, destroy=destroy)
            action = "permanently destroyed" if destroy else "moved to recycle bin"
            return json.dumps({"message": f"Work item {work_item_id} {action} successfully."}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error deleting work item {work_item_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error deleting work item {work_item_id}")
            return self._json_error(str(e))

    def list_work_item_comments(
        self,
        work_item_id: int,
        project: Optional[str] = None,
    ) -> str:
        """
        List comments on a work item.

        Args:
            work_item_id: The numeric ID of the work item.
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing the list of comments.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            wit_client = conn.clients.get_work_item_tracking_client()
            log_debug(f"Listing comments for work item: {work_item_id}")
            comments_result = wit_client.get_comments(project=project, work_item_id=work_item_id)
            data = [
                {
                    "id": c.id,
                    "text": c.text,
                    "created_by": c.created_by.display_name if getattr(c, "created_by", None) else None,
                    "created_date": c.created_date.isoformat() if getattr(c, "created_date", None) else None,
                    "modified_date": c.modified_date.isoformat() if getattr(c, "modified_date", None) else None,
                    "url": getattr(c, "url", None),
                }
                for c in (comments_result.comments or [])
            ]
            return json.dumps({"data": data, "meta": {"returned_items": len(data)}}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error listing work item comments: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error listing work item comments")
            return self._json_error(str(e))

    def add_work_item_comment(
        self,
        work_item_id: int,
        text: str,
        project: Optional[str] = None,
    ) -> str:
        """
        Add a comment to a work item.

        Args:
            work_item_id: The numeric ID of the work item.
            text: The comment text (HTML supported).
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing the created comment details.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            wit_client = conn.clients.get_work_item_tracking_client()
            comment_create = CommentCreate(text=text)
            log_debug(f"Adding comment to work item: {work_item_id}")
            comment = wit_client.add_comment(request=comment_create, project=project, work_item_id=work_item_id)
            return json.dumps(
                {
                    "id": comment.id,
                    "text": comment.text,
                    "created_by": comment.created_by.display_name if getattr(comment, "created_by", None) else None,
                    "created_date": comment.created_date.isoformat()
                    if getattr(comment, "created_date", None)
                    else None,
                    "url": getattr(comment, "url", None),
                },
                indent=2,
            )
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error adding work item comment: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error adding work item comment")
            return self._json_error(str(e))

    #  PIPELINES / BUILDS

    def list_pipelines(
        self,
        project: Optional[str] = None,
        name_filter: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> str:
        """
        List build pipeline definitions in a project.

        Args:
            project: Project name or ID. Defaults to the toolkit's configured project.
            name_filter: Optional filter to match pipeline names.
            page: Page number for pagination (1-based).
            per_page: Number of items per page (max 100).

        Returns:
            JSON string containing pipeline data and pagination metadata.
        """
        try:
            per_page = self._bound_page_size(per_page)
            project = self._resolve_project(project)
            conn = self._get_connection()
            build_client = conn.clients.get_build_client()
            log_debug(f"Listing pipelines for project: {project}")
            all_defs = list(build_client.get_definitions(project=project, name=name_filter))
            start = (page - 1) * per_page
            page_items = all_defs[start : start + per_page]
            data = [self._serialize_pipeline(d) for d in page_items]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error listing pipelines: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error listing pipelines")
            return self._json_error(str(e))

    def trigger_pipeline(
        self,
        pipeline_id: int,
        project: Optional[str] = None,
        source_branch: Optional[str] = None,
        parameters: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        Trigger (queue) a build pipeline run.

        Args:
            pipeline_id: The numeric ID of the pipeline / build definition.
            project: Project name or ID. Defaults to the toolkit's configured project.
            source_branch: Branch to run against (e.g. 'refs/heads/main').
            parameters: Optional dict of queue-time parameter name → value pairs.

        Returns:
            JSON string containing the queued build details.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            build_client = conn.clients.get_build_client()
            definition = BuildDefinitionReference(id=pipeline_id)
            build = Build(
                definition=definition,
                source_branch=source_branch,
                parameters=json.dumps(parameters) if parameters else None,
            )
            log_debug(f"Triggering pipeline {pipeline_id} in project: {project}")
            queued_build = build_client.queue_build(build=build, project=project)
            return json.dumps(self._serialize_build(queued_build), indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error triggering pipeline {pipeline_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error triggering pipeline {pipeline_id}")
            return self._json_error(str(e))

    def get_pipeline_runs(
        self,
        pipeline_id: int,
        project: Optional[str] = None,
        status_filter: Optional[str] = None,
        branch_name: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> str:
        """
        Get recent runs (builds) for a pipeline.

        Args:
            pipeline_id: The numeric ID of the pipeline / build definition.
            project: Project name or ID. Defaults to the toolkit's configured project.
            status_filter: Optional status: 'inProgress', 'completed', 'cancelling', 'notStarted', 'all'.
            branch_name: Optional branch filter (e.g. 'refs/heads/main').
            page: Page number for pagination (1-based).
            per_page: Number of items per page (max 100).

        Returns:
            JSON string containing build run data and pagination metadata.
        """
        try:
            per_page = self._bound_page_size(per_page)
            project = self._resolve_project(project)
            conn = self._get_connection()
            build_client = conn.clients.get_build_client()
            log_debug(f"Getting runs for pipeline {pipeline_id}")
            all_builds = list(
                build_client.get_builds(
                    project=project,
                    definitions=[pipeline_id],
                    status_filter=status_filter,
                    branch_name=branch_name,
                    top=per_page * page,
                )
            )
            start = (page - 1) * per_page
            page_items = all_builds[start : start + per_page]
            data = [self._serialize_build(b) for b in page_items]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error getting pipeline runs: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error getting pipeline runs")
            return self._json_error(str(e))

    def cancel_build(self, build_id: int, project: Optional[str] = None) -> str:
        """
        Cancel a running build.

        Args:
            build_id: The numeric ID of the build to cancel.
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string confirming cancellation.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            build_client = conn.clients.get_build_client()
            log_debug(f"Cancelling build: {build_id}")
            build_client.update_build(
                build=Build(status="cancelling"),
                project=project,
                build_id=build_id,
            )
            return json.dumps({"message": f"Build {build_id} cancellation requested."}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error cancelling build {build_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error cancelling build {build_id}")
            return self._json_error(str(e))

    def get_build_logs(self, build_id: int, project: Optional[str] = None) -> str:
        """
        Get the log entries for a build.

        Args:
            build_id: The numeric ID of the build.
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing a list of log entries with their IDs, URLs, and line counts.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            build_client = conn.clients.get_build_client()
            log_debug(f"Getting logs for build: {build_id}")
            logs = build_client.get_build_logs(project=project, build_id=build_id)
            data = [
                {
                    "id": log.id,
                    "type": getattr(log, "type", None),
                    "url": getattr(log, "url", None),
                    "created_on": log.created_on.isoformat() if getattr(log, "created_on", None) else None,
                    "last_changed_on": log.last_changed_on.isoformat()
                    if getattr(log, "last_changed_on", None)
                    else None,
                    "line_count": getattr(log, "line_count", None),
                }
                for log in logs
            ]
            return json.dumps({"data": data, "meta": {"returned_items": len(data)}}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error getting build logs {build_id}: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception(f"Unexpected error getting build logs {build_id}")
            return self._json_error(str(e))

    #  RELEASES

    def list_release_definitions(
        self,
        project: Optional[str] = None,
        name_filter: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> str:
        """
        List release pipeline definitions in a project.

        Args:
            project: Project name or ID. Defaults to the toolkit's configured project.
            name_filter: Optional filter on definition name.
            page: Page number for pagination (1-based).
            per_page: Number of items per page (max 100).

        Returns:
            JSON string containing release definition data and pagination metadata.
        """
        try:
            per_page = self._bound_page_size(per_page)
            project = self._resolve_project(project)
            conn = self._get_connection()
            release_client = conn.clients.get_release_client()
            log_debug(f"Listing release definitions for project: {project}")
            all_defs = list(release_client.get_release_definitions(project=project, search_text=name_filter))
            start = (page - 1) * per_page
            page_items = all_defs[start : start + per_page]
            data = [self._serialize_release_definition(rd) for rd in page_items]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error listing release definitions: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error listing release definitions")
            return self._json_error(str(e))

    def list_releases(
        self,
        project: Optional[str] = None,
        definition_id: Optional[int] = None,
        status_filter: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> str:
        """
        List releases in a project.

        Args:
            project: Project name or ID. Defaults to the toolkit's configured project.
            definition_id: Optional release definition ID to filter by.
            status_filter: Optional status filter: 'active', 'abandoned', 'draft', 'undefined'.
            page: Page number for pagination (1-based).
            per_page: Number of items per page (max 100).

        Returns:
            JSON string containing release data and pagination metadata.
        """
        try:
            per_page = self._bound_page_size(per_page)
            project = self._resolve_project(project)
            conn = self._get_connection()
            release_client = conn.clients.get_release_client()
            log_debug(f"Listing releases for project: {project}")
            all_releases = list(
                release_client.get_releases(
                    project=project,
                    definition_id=definition_id,
                    status_filter=status_filter,
                    top=per_page * page,
                )
            )
            start = (page - 1) * per_page
            page_items = all_releases[start : start + per_page]
            data = [self._serialize_release(r) for r in page_items]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error listing releases: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error listing releases")
            return self._json_error(str(e))

    def create_release(
        self,
        definition_id: int,
        project: Optional[str] = None,
        description: Optional[str] = None,
        artifacts: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Create a new release from a release definition.

        Args:
            definition_id: The numeric ID of the release definition.
            project: Project name or ID. Defaults to the toolkit's configured project.
            description: Optional release description.
            artifacts: Optional list of artifact metadata dicts to override.

        Returns:
            JSON string containing the created release details.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            release_client = conn.clients.get_release_client()
            from azure.devops.v7_0.release.models import ReleaseStartMetadata  # type: ignore

            metadata = ReleaseStartMetadata(
                definition_id=definition_id,
                description=description,
                artifacts=artifacts or [],
            )
            log_debug(f"Creating release for definition {definition_id} in project: {project}")
            release = release_client.create_release(release_start_metadata=metadata, project=project)
            return json.dumps(self._serialize_release(release), indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error creating release: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error creating release")
            return self._json_error(str(e))

    #  TEAMS

    def list_teams(
        self,
        project: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> str:
        """
        List teams in a project.

        Args:
            project: Project name or ID. Defaults to the toolkit's configured project.
            page: Page number for pagination (1-based).
            per_page: Number of items per page (max 100).

        Returns:
            JSON string containing team data and pagination metadata.
        """
        try:
            per_page = self._bound_page_size(per_page)
            project = self._resolve_project(project)
            conn = self._get_connection()
            core_client = conn.clients.get_core_client()
            log_debug(f"Listing teams for project: {project}")
            all_teams = list(core_client.get_teams(project_id=project))
            start = (page - 1) * per_page
            page_items = all_teams[start : start + per_page]
            data = [self._serialize_team(t) for t in page_items]
            return json.dumps({"data": data, "meta": self._build_meta(page, per_page, len(data))}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error listing teams: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error listing teams")
            return self._json_error(str(e))

    def get_team_members(self, team_id: str, project: Optional[str] = None) -> str:
        """
        Get members of a specific team.

        Args:
            team_id: Team ID or name.
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing team member data.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            core_client = conn.clients.get_core_client()
            log_debug(f"Getting members for team: {team_id}")
            members = core_client.get_team_members_with_extended_properties(project_id=project, team_id=team_id)
            data = [self._serialize_team_member(m) for m in members]
            return json.dumps({"data": data, "meta": {"returned_items": len(data)}}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error getting team members: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error getting team members")
            return self._json_error(str(e))

    #  ITERATIONS / SPRINTS

    def list_iterations(
        self,
        team: Optional[str] = None,
        project: Optional[str] = None,
        time_frame: Optional[str] = None,
    ) -> str:
        """
        List iterations (sprints) for a team.

        Args:
            team: Team name or ID. Defaults to the project's default team.
            project: Project name or ID. Defaults to the toolkit's configured project.
            time_frame: Optional filter: 'current', 'past', or 'future'.

        Returns:
            JSON string containing iteration data.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            work_client = conn.clients.get_work_client()
            from azure.devops.v7_0.work.models import TeamContext  # type: ignore

            team_context = TeamContext(project=project, team=team)
            log_debug(f"Listing iterations for project: {project}, team: {team}")
            try:
                iterations = work_client.get_team_iterations(team_context=team_context, timeframe=time_frame)
            except Exception as tf_err:
                if "timeframe" in str(tf_err).lower():
                    return json.dumps({"data": [], "meta": {"returned_items": 0}}, indent=2)
                raise
            data = [self._serialize_iteration(i) for i in (iterations or [])]
            return json.dumps({"data": data, "meta": {"returned_items": len(data)}}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error listing iterations: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error listing iterations")
            return self._json_error(str(e))

    def get_iteration_work_items(
        self,
        iteration_id: str,
        team: Optional[str] = None,
        project: Optional[str] = None,
    ) -> str:
        """
        Get work items assigned to a specific iteration (sprint).

        Args:
            iteration_id: The GUID of the iteration.
            team: Team name or ID. Defaults to the project's default team.
            project: Project name or ID. Defaults to the toolkit's configured project.

        Returns:
            JSON string containing the work items in the iteration.
        """
        try:
            project = self._resolve_project(project)
            conn = self._get_connection()
            work_client = conn.clients.get_work_client()
            wit_client = conn.clients.get_work_item_tracking_client()
            from azure.devops.v7_0.work.models import TeamContext

            team_context = TeamContext(project=project, team=team)
            log_debug(f"Getting work items for iteration: {iteration_id}")
            iteration_work_items = work_client.get_iteration_work_items(
                team_context=team_context,
                iteration_id=iteration_id,
            )
            relations = getattr(iteration_work_items, "work_item_relations", []) or []
            ids = [rel.target.id for rel in relations if rel.target]
            if not ids:
                return json.dumps({"data": [], "meta": {"returned_items": 0}}, indent=2)
            work_items = wit_client.get_work_items(ids=ids, error_policy="omit")
            data = [self._serialize_work_item(wi) for wi in work_items if wi is not None]
            return json.dumps({"data": data, "meta": {"returned_items": len(data)}}, indent=2)
        except (AzureDevOpsAuthenticationError, AzureDevOpsServiceError) as e:
            logger.error(f"Azure DevOps error getting iteration work items: {e}")
            return self._json_error(str(e))
        except Exception as e:
            logger.exception("Unexpected error getting iteration work items")
            return self._json_error(str(e))
