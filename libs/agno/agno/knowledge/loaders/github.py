"""GitHub content loader for Knowledge.

Provides methods for loading content from GitHub repositories.
"""

# mypy: disable-error-code="attr-defined"

from io import BytesIO
from typing import Dict, List, Optional, cast

import httpx
from httpx import AsyncClient

from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.reader import Reader
from agno.knowledge.remote_content.config import GitHubConfig, RemoteContentConfig
from agno.knowledge.remote_content.remote_content import GitHubContent
from agno.utils.log import log_error, log_warning
from agno.utils.string import generate_id


class GitHubLoader:
    """Loader for GitHub content."""

    async def _aload_from_github(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[RemoteContentConfig] = None,
    ):
        """Load content from GitHub.

        Requires the GitHub config to contain repo and optionally token for private repos.
        Uses the GitHub API to fetch file contents.
        """
        remote_content: GitHubContent = cast(GitHubContent, content.remote_content)
        gh_config = cast(GitHubConfig, config) if isinstance(config, GitHubConfig) else None

        if gh_config is None:
            log_error(f"GitHub config not found for config_id: {remote_content.config_id}")
            return

        # Build headers for GitHub API
        headers: Dict[str, str] = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Agno-Knowledge",
        }
        if gh_config.token:
            headers["Authorization"] = f"Bearer {gh_config.token}"

        branch = remote_content.branch or gh_config.branch or "main"

        # Get list of files to process
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

                    # If items is not a list, it's a single file response
                    if not isinstance(items, list):
                        items = [items]

                    for item in items:
                        if item.get("type") == "file":
                            files.append(
                                {
                                    "path": item["path"],
                                    "name": item["name"],
                                }
                            )
                        elif item.get("type") == "dir":
                            # Recursively get files from subdirectory
                            subdir_files = await list_files_recursive(item["path"])
                            files.extend(subdir_files)
                except Exception as e:
                    log_error(f"Error listing GitHub folder {folder}: {e}")

                return files

            # Get the path to process (file_path or folder_path)
            path_to_process = (remote_content.file_path or remote_content.folder_path or "").rstrip("/")

            if path_to_process:
                # Fetch the path to determine if it's a file or directory
                api_url = f"https://api.github.com/repos/{gh_config.repo}/contents/{path_to_process}"
                if branch:
                    api_url += f"?ref={branch}"

                try:
                    response = await client.get(api_url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    path_data = response.json()

                    if isinstance(path_data, list):
                        # It's a directory - recursively list all files
                        for item in path_data:
                            if item.get("type") == "file":
                                files_to_process.append({"path": item["path"], "name": item["name"]})
                            elif item.get("type") == "dir":
                                subdir_files = await list_files_recursive(item["path"])
                                files_to_process.extend(subdir_files)
                    else:
                        # It's a single file
                        files_to_process.append(
                            {
                                "path": path_data["path"],
                                "name": path_data["name"],
                            }
                        )
                except Exception as e:
                    log_error(f"Error fetching GitHub path {path_to_process}: {e}")
                    return

            if not files_to_process:
                log_warning(f"No files found at GitHub path: {path_to_process}")
                return

            # Process each file
            for file_info in files_to_process:
                file_path = file_info["path"]
                file_name = file_info["name"]

                # Build a unique virtual path for hashing (ensures different files don't collide)
                virtual_path = f"github://{gh_config.repo}/{branch}/{file_path}"

                # Build metadata with all info needed to re-fetch the file
                github_metadata: Dict[str, str] = {
                    "source_type": "github",
                    "source_config_id": gh_config.id,
                    "source_config_name": gh_config.name,
                    "github_repo": gh_config.repo,
                    "github_branch": branch,
                    "github_path": file_path,
                    "github_filename": file_name,
                }
                # Merge with user-provided metadata (user metadata takes precedence)
                merged_metadata = {**github_metadata, **(content.metadata or {})}

                # Setup Content object
                # Naming: for folders, use relative path; for single files, use user name or filename
                is_folder_upload = len(files_to_process) > 1
                if is_folder_upload:
                    # Compute relative path from the upload root
                    relative_path = file_path
                    if path_to_process and file_path.startswith(path_to_process + "/"):
                        relative_path = file_path[len(path_to_process) + 1 :]
                    # If user provided a name, prefix it; otherwise use full file path
                    content_name = f"{content.name}/{relative_path}" if content.name else file_path
                else:
                    # Single file: use user's name or the filename
                    content_name = content.name or file_name
                content_entry = Content(
                    name=content_name,
                    description=content.description,
                    path=virtual_path,  # Include path for unique hashing
                    status=ContentStatus.PROCESSING,
                    metadata=merged_metadata,
                    file_type="github",
                )

                # Hash content and add to contents database
                content_entry.content_hash = self._build_content_hash(content_entry)
                content_entry.id = generate_id(content_entry.content_hash)
                await self._ainsert_contents_db(content_entry)

                if self._should_skip(content_entry.content_hash, skip_if_exists):
                    content_entry.status = ContentStatus.COMPLETED
                    await self._aupdate_content(content_entry)
                    continue

                # Fetch file content using GitHub API (works for private repos)
                api_url = f"https://api.github.com/repos/{gh_config.repo}/contents/{file_path}"
                if branch:
                    api_url += f"?ref={branch}"
                try:
                    response = await client.get(api_url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    file_data = response.json()

                    # GitHub API returns content as base64
                    if file_data.get("encoding") == "base64":
                        import base64

                        file_content = base64.b64decode(file_data["content"])
                    else:
                        # For large files, GitHub returns a download_url
                        download_url = file_data.get("download_url")
                        if download_url:
                            dl_response = await client.get(download_url, headers=headers, timeout=30.0)
                            dl_response.raise_for_status()
                            file_content = dl_response.content
                        else:
                            raise ValueError("No content or download_url in response")
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
        """Synchronous version of _load_from_github."""
        remote_content: GitHubContent = cast(GitHubContent, content.remote_content)
        gh_config = cast(GitHubConfig, config) if isinstance(config, GitHubConfig) else None

        if gh_config is None:
            log_error(f"GitHub config not found for config_id: {remote_content.config_id}")
            return

        # Build headers for GitHub API
        headers: Dict[str, str] = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Agno-Knowledge",
        }
        if gh_config.token:
            headers["Authorization"] = f"Bearer {gh_config.token}"

        branch = remote_content.branch or gh_config.branch or "main"

        # Get list of files to process
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

                    # If items is not a list, it's a single file response
                    if not isinstance(items, list):
                        items = [items]

                    for item in items:
                        if item.get("type") == "file":
                            files.append(
                                {
                                    "path": item["path"],
                                    "name": item["name"],
                                }
                            )
                        elif item.get("type") == "dir":
                            # Recursively get files from subdirectory
                            subdir_files = list_files_recursive(item["path"])
                            files.extend(subdir_files)
                except Exception as e:
                    log_error(f"Error listing GitHub folder {folder}: {e}")

                return files

            # Get the path to process (file_path or folder_path)
            path_to_process = (remote_content.file_path or remote_content.folder_path or "").rstrip("/")

            if path_to_process:
                # Fetch the path to determine if it's a file or directory
                api_url = f"https://api.github.com/repos/{gh_config.repo}/contents/{path_to_process}"
                if branch:
                    api_url += f"?ref={branch}"

                try:
                    response = client.get(api_url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    path_data = response.json()

                    if isinstance(path_data, list):
                        # It's a directory - recursively list all files
                        for item in path_data:
                            if item.get("type") == "file":
                                files_to_process.append({"path": item["path"], "name": item["name"]})
                            elif item.get("type") == "dir":
                                subdir_files = list_files_recursive(item["path"])
                                files_to_process.extend(subdir_files)
                    else:
                        # It's a single file
                        files_to_process.append(
                            {
                                "path": path_data["path"],
                                "name": path_data["name"],
                            }
                        )
                except Exception as e:
                    log_error(f"Error fetching GitHub path {path_to_process}: {e}")
                    return

            if not files_to_process:
                log_warning(f"No files found at GitHub path: {path_to_process}")
                return

            # Process each file
            for file_info in files_to_process:
                file_path = file_info["path"]
                file_name = file_info["name"]

                # Build a unique virtual path for hashing (ensures different files don't collide)
                virtual_path = f"github://{gh_config.repo}/{branch}/{file_path}"

                # Build metadata with all info needed to re-fetch the file
                github_metadata: Dict[str, str] = {
                    "source_type": "github",
                    "source_config_id": gh_config.id,
                    "source_config_name": gh_config.name,
                    "github_repo": gh_config.repo,
                    "github_branch": branch,
                    "github_path": file_path,
                    "github_filename": file_name,
                }
                # Merge with user-provided metadata (user metadata takes precedence)
                merged_metadata = {**github_metadata, **(content.metadata or {})}

                # Setup Content object
                # Naming: for folders, use relative path; for single files, use user name or filename
                is_folder_upload = len(files_to_process) > 1
                if is_folder_upload:
                    # Compute relative path from the upload root
                    relative_path = file_path
                    if path_to_process and file_path.startswith(path_to_process + "/"):
                        relative_path = file_path[len(path_to_process) + 1 :]
                    # If user provided a name, prefix it; otherwise use full file path
                    content_name = f"{content.name}/{relative_path}" if content.name else file_path
                else:
                    # Single file: use user's name or the filename
                    content_name = content.name or file_name
                content_entry = Content(
                    name=content_name,
                    description=content.description,
                    path=virtual_path,  # Include path for unique hashing
                    status=ContentStatus.PROCESSING,
                    metadata=merged_metadata,
                    file_type="github",
                )

                # Hash content and add to contents database
                content_entry.content_hash = self._build_content_hash(content_entry)
                content_entry.id = generate_id(content_entry.content_hash)
                self._insert_contents_db(content_entry)

                if self._should_skip(content_entry.content_hash, skip_if_exists):
                    content_entry.status = ContentStatus.COMPLETED
                    self._update_content(content_entry)
                    continue

                # Fetch file content using GitHub API (works for private repos)
                api_url = f"https://api.github.com/repos/{gh_config.repo}/contents/{file_path}"
                if branch:
                    api_url += f"?ref={branch}"
                try:
                    response = client.get(api_url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    file_data = response.json()

                    # GitHub API returns content as base64
                    if file_data.get("encoding") == "base64":
                        import base64

                        file_content = base64.b64decode(file_data["content"])
                    else:
                        # For large files, GitHub returns a download_url
                        download_url = file_data.get("download_url")
                        if download_url:
                            dl_response = client.get(download_url, headers=headers, timeout=30.0)
                            dl_response.raise_for_status()
                            file_content = dl_response.content
                        else:
                            raise ValueError("No content or download_url in response")
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
