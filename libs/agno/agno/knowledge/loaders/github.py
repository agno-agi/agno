"""GitHub content loader for Knowledge.

Provides methods for loading content from GitHub repositories.
"""

# mypy: disable-error-code="attr-defined"

from io import BytesIO
from typing import Dict, List, Optional, cast

import httpx
from httpx import AsyncClient

from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.loaders.base import BaseLoader
from agno.knowledge.reader import Reader
from agno.knowledge.remote_content.config import GitHubConfig, RemoteContentConfig
from agno.knowledge.remote_content.remote_content import GitHubContent
from agno.utils.log import log_error, log_info, log_warning
from agno.utils.string import generate_id


class GitHubLoader(BaseLoader):
    """Loader for GitHub content."""

    # ==========================================
    # GITHUB HELPERS (shared between sync/async)
    # ==========================================

    def _validate_github_config(
        self,
        content: Content,
        config: Optional[RemoteContentConfig],
    ) -> Optional[GitHubConfig]:
        """Validate and extract GitHub config.

        Returns:
            GitHubConfig if valid, None otherwise
        """
        remote_content: GitHubContent = cast(GitHubContent, content.remote_content)
        gh_config = cast(GitHubConfig, config) if isinstance(config, GitHubConfig) else None

        if gh_config is None:
            log_error(f"GitHub config not found for config_id: {remote_content.config_id}")
            return None

        return gh_config

    def _build_github_headers(self, gh_config: GitHubConfig) -> Dict[str, str]:
        """Build headers for GitHub API requests."""
        headers: Dict[str, str] = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Agno-Knowledge",
        }
        if gh_config.token:
            headers["Authorization"] = f"Bearer {gh_config.token}"
        return headers

    def _build_github_metadata(
        self,
        gh_config: GitHubConfig,
        branch: str,
        file_path: str,
        file_name: str,
    ) -> Dict[str, str]:
        """Build GitHub-specific metadata dictionary."""
        return {
            "source_type": "github",
            "source_config_id": gh_config.id,
            "source_config_name": gh_config.name,
            "github_repo": gh_config.repo,
            "github_branch": branch,
            "github_path": file_path,
            "github_filename": file_name,
        }

    def _build_github_virtual_path(self, repo: str, branch: str, file_path: str) -> str:
        """Build virtual path for GitHub content."""
        return f"github://{repo}/{branch}/{file_path}"

    def _get_github_branch(self, remote_content: GitHubContent, gh_config: GitHubConfig) -> str:
        """Get the branch to use for GitHub operations."""
        return remote_content.branch or gh_config.branch or "main"

    def _get_github_path_to_process(self, remote_content: GitHubContent) -> str:
        """Get the path to process from remote content."""
        return (remote_content.file_path or remote_content.folder_path or "").rstrip("/")

    def _process_github_file_content(
        self,
        file_data: dict,
        client: httpx.Client,
        headers: Dict[str, str],
    ) -> bytes:
        """Process GitHub API response and return file content (sync)."""
        if file_data.get("encoding") == "base64":
            import base64

            return base64.b64decode(file_data["content"])
        else:
            download_url = file_data.get("download_url")
            if download_url:
                dl_response = client.get(download_url, headers=headers, timeout=30.0)
                dl_response.raise_for_status()
                return dl_response.content
            else:
                raise ValueError("No content or download_url in response")

    async def _aprocess_github_file_content(
        self,
        file_data: dict,
        client: AsyncClient,
        headers: Dict[str, str],
    ) -> bytes:
        """Process GitHub API response and return file content (async)."""
        if file_data.get("encoding") == "base64":
            import base64

            return base64.b64decode(file_data["content"])
        else:
            download_url = file_data.get("download_url")
            if download_url:
                dl_response = await client.get(download_url, headers=headers, timeout=30.0)
                dl_response.raise_for_status()
                return dl_response.content
            else:
                raise ValueError("No content or download_url in response")

    # ==========================================
    # GITHUB LOADERS
    # ==========================================

    async def _aload_from_github(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[RemoteContentConfig] = None,
    ):
        """Load content from GitHub (async).

        Requires the GitHub config to contain repo and optionally token for private repos.
        Uses the GitHub API to fetch file contents.
        """
        remote_content: GitHubContent = cast(GitHubContent, content.remote_content)
        gh_config = self._validate_github_config(content, config)
        if gh_config is None:
            return

        headers = self._build_github_headers(gh_config)
        branch = self._get_github_branch(remote_content, gh_config)
        path_to_process = self._get_github_path_to_process(remote_content)

        files_to_process: List[Dict[str, str]] = []

        async with AsyncClient() as client:
            # Helper function to recursively list all files in a folder
            async def list_files_recursive(folder: str) -> List[Dict[str, str]]:
                """Recursively list all files in a GitHub folder."""
                files: List[Dict[str, str]] = []
                api_url = f"https://api.github.com/repos/{gh_config.repo}/contents/{folder}"
                if branch:
                    api_url += f"?ref={branch}"

                try:
                    response = await client.get(api_url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    items = response.json()

                    if not isinstance(items, list):
                        items = [items]

                    for item in items:
                        if item.get("type") == "file":
                            files.append({"path": item["path"], "name": item["name"]})
                        elif item.get("type") == "dir":
                            subdir_files = await list_files_recursive(item["path"])
                            files.extend(subdir_files)
                except Exception as e:
                    log_error(f"Error listing GitHub folder {folder}: {e}")

                return files

            if path_to_process:
                api_url = f"https://api.github.com/repos/{gh_config.repo}/contents/{path_to_process}"
                if branch:
                    api_url += f"?ref={branch}"

                try:
                    response = await client.get(api_url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    path_data = response.json()

                    if isinstance(path_data, list):
                        for item in path_data:
                            if item.get("type") == "file":
                                files_to_process.append({"path": item["path"], "name": item["name"]})
                            elif item.get("type") == "dir":
                                subdir_files = await list_files_recursive(item["path"])
                                files_to_process.extend(subdir_files)
                    else:
                        files_to_process.append({"path": path_data["path"], "name": path_data["name"]})
                except Exception as e:
                    log_error(f"Error fetching GitHub path {path_to_process}: {e}")
                    return

            if not files_to_process:
                log_warning(f"No files found at GitHub path: {path_to_process}")
                return

            log_info(f"Processing {len(files_to_process)} file(s) from GitHub")
            is_folder_upload = len(files_to_process) > 1

            for file_info in files_to_process:
                file_path = file_info["path"]
                file_name = file_info["name"]

                # Build metadata and virtual path using helpers
                virtual_path = self._build_github_virtual_path(gh_config.repo, branch, file_path)
                github_metadata = self._build_github_metadata(gh_config, branch, file_path, file_name)
                merged_metadata = self._merge_metadata(github_metadata, content.metadata)

                # Compute content name using base helper
                content_name = self._compute_content_name(
                    file_path, file_name, content.name, path_to_process, is_folder_upload
                )

                # Create content entry using base helper
                content_entry = self._create_content_entry(
                    content, content_name, virtual_path, merged_metadata, "github", is_folder_upload
                )

                await self._ainsert_contents_db(content_entry)

                if self._should_skip(content_entry.content_hash, skip_if_exists):
                    content_entry.status = ContentStatus.COMPLETED
                    await self._aupdate_content(content_entry)
                    continue

                # Fetch file content
                api_url = f"https://api.github.com/repos/{gh_config.repo}/contents/{file_path}"
                if branch:
                    api_url += f"?ref={branch}"
                try:
                    response = await client.get(api_url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    file_data = response.json()
                    file_content = await self._aprocess_github_file_content(file_data, client, headers)
                except Exception as e:
                    log_error(f"Error fetching GitHub file {file_path}: {e}")
                    content_entry.status = ContentStatus.FAILED
                    content_entry.status_message = str(e)
                    await self._aupdate_content(content_entry)
                    continue

                # Select reader and read content
                reader = self._select_reader_by_uri(file_name, content.reader)
                if reader is None:
                    log_warning(f"No reader found for file: {file_name}")
                    content_entry.status = ContentStatus.FAILED
                    content_entry.status_message = "No suitable reader found"
                    await self._aupdate_content(content_entry)
                    continue

                reader = cast(Reader, reader)
                readable_content = BytesIO(file_content)
                read_documents = await reader.async_read(readable_content, name=file_name)

                # Prepare and insert into vector database
                if not content_entry.id:
                    content_entry.id = generate_id(content_entry.content_hash or "")
                self._prepare_documents_for_insert(read_documents, content_entry.id)
                await self._ahandle_vector_db_insert(content_entry, read_documents, upsert)

    def _load_from_github(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[RemoteContentConfig] = None,
    ):
        """Load content from GitHub (sync).

        Requires the GitHub config to contain repo and optionally token for private repos.
        Uses the GitHub API to fetch file contents.
        """
        remote_content: GitHubContent = cast(GitHubContent, content.remote_content)
        gh_config = self._validate_github_config(content, config)
        if gh_config is None:
            return

        headers = self._build_github_headers(gh_config)
        branch = self._get_github_branch(remote_content, gh_config)
        path_to_process = self._get_github_path_to_process(remote_content)

        files_to_process: List[Dict[str, str]] = []

        with httpx.Client() as client:
            # Helper function to recursively list all files in a folder
            def list_files_recursive(folder: str) -> List[Dict[str, str]]:
                """Recursively list all files in a GitHub folder."""
                files: List[Dict[str, str]] = []
                api_url = f"https://api.github.com/repos/{gh_config.repo}/contents/{folder}"
                if branch:
                    api_url += f"?ref={branch}"

                try:
                    response = client.get(api_url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    items = response.json()

                    if not isinstance(items, list):
                        items = [items]

                    for item in items:
                        if item.get("type") == "file":
                            files.append({"path": item["path"], "name": item["name"]})
                        elif item.get("type") == "dir":
                            subdir_files = list_files_recursive(item["path"])
                            files.extend(subdir_files)
                except Exception as e:
                    log_error(f"Error listing GitHub folder {folder}: {e}")

                return files

            if path_to_process:
                api_url = f"https://api.github.com/repos/{gh_config.repo}/contents/{path_to_process}"
                if branch:
                    api_url += f"?ref={branch}"

                try:
                    response = client.get(api_url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    path_data = response.json()

                    if isinstance(path_data, list):
                        for item in path_data:
                            if item.get("type") == "file":
                                files_to_process.append({"path": item["path"], "name": item["name"]})
                            elif item.get("type") == "dir":
                                subdir_files = list_files_recursive(item["path"])
                                files_to_process.extend(subdir_files)
                    else:
                        files_to_process.append({"path": path_data["path"], "name": path_data["name"]})
                except Exception as e:
                    log_error(f"Error fetching GitHub path {path_to_process}: {e}")
                    return

            if not files_to_process:
                log_warning(f"No files found at GitHub path: {path_to_process}")
                return

            log_info(f"Processing {len(files_to_process)} file(s) from GitHub")
            is_folder_upload = len(files_to_process) > 1

            for file_info in files_to_process:
                file_path = file_info["path"]
                file_name = file_info["name"]

                # Build metadata and virtual path using helpers
                virtual_path = self._build_github_virtual_path(gh_config.repo, branch, file_path)
                github_metadata = self._build_github_metadata(gh_config, branch, file_path, file_name)
                merged_metadata = self._merge_metadata(github_metadata, content.metadata)

                # Compute content name using base helper
                content_name = self._compute_content_name(
                    file_path, file_name, content.name, path_to_process, is_folder_upload
                )

                # Create content entry using base helper
                content_entry = self._create_content_entry(
                    content, content_name, virtual_path, merged_metadata, "github", is_folder_upload
                )

                self._insert_contents_db(content_entry)

                if self._should_skip(content_entry.content_hash, skip_if_exists):
                    content_entry.status = ContentStatus.COMPLETED
                    self._update_content(content_entry)
                    continue

                # Fetch file content
                api_url = f"https://api.github.com/repos/{gh_config.repo}/contents/{file_path}"
                if branch:
                    api_url += f"?ref={branch}"
                try:
                    response = client.get(api_url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    file_data = response.json()
                    file_content = self._process_github_file_content(file_data, client, headers)
                except Exception as e:
                    log_error(f"Error fetching GitHub file {file_path}: {e}")
                    content_entry.status = ContentStatus.FAILED
                    content_entry.status_message = str(e)
                    self._update_content(content_entry)
                    continue

                # Select reader and read content
                reader = self._select_reader_by_uri(file_name, content.reader)
                if reader is None:
                    log_warning(f"No reader found for file: {file_name}")
                    content_entry.status = ContentStatus.FAILED
                    content_entry.status_message = "No suitable reader found"
                    self._update_content(content_entry)
                    continue

                reader = cast(Reader, reader)
                readable_content = BytesIO(file_content)
                read_documents = reader.read(readable_content, name=file_name)

                # Prepare and insert into vector database
                if not content_entry.id:
                    content_entry.id = generate_id(content_entry.content_hash or "")
                self._prepare_documents_for_insert(read_documents, content_entry.id)
                self._handle_vector_db_insert(content_entry, read_documents, upsert)
