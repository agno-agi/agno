"""GitHub content loader for Knowledge.

Provides methods for loading content from GitHub repositories.
"""

# mypy: disable-error-code="attr-defined"

import asyncio
import threading
import time
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple, cast

import httpx
from httpx import AsyncClient

from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.loaders.base import BaseLoader
from agno.knowledge.reader import Reader
from agno.knowledge.remote_content.base import BaseStorageConfig
from agno.knowledge.remote_content.github import GitHubConfig
from agno.knowledge.remote_content.remote_content import GitHubContent
from agno.utils.log import log_error, log_info, log_warning
from agno.utils.string import generate_id


class GitHubLoader(BaseLoader):
    """Loader for GitHub content."""

    # Cache for GitHub App installation tokens: {cache_key: (token, expires_at_timestamp)}
    # Uses double-checked locking: lock-free fast path for cache hits,
    # lock only on cache miss to coordinate token refresh.
    _github_app_token_cache: Dict[str, tuple] = {}
    _token_cache_lock = threading.Lock()
    _async_token_cache_lock: Optional[asyncio.Lock] = None

    # ==========================================
    # GITHUB HELPERS (shared between sync/async)
    # ==========================================

    @staticmethod
    def _check_cached_token(cache: Dict[str, tuple], cache_key: str) -> Optional[str]:
        """Return a cached token if it is still valid (60s buffer), else None."""
        cached = cache.get(cache_key)
        if cached is not None:
            token, expires_at = cached
            if time.time() < expires_at - 60:
                return token
        return None

    @staticmethod
    def _build_jwt_and_url(gh_config: GitHubConfig) -> Tuple[str, Dict[str, str]]:
        """Build a signed JWT and return (exchange_url, headers).

        Raises ImportError if PyJWT is not installed.
        """
        try:
            import jwt
        except ImportError:
            raise ImportError(
                "GitHub App authentication requires PyJWT with cryptography. "
                "Install via: pip install PyJWT cryptography"
            )

        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + 600,
            "iss": str(gh_config.app_id),
        }
        private_key = gh_config.private_key
        if private_key is None:
            raise ValueError("private_key is required for GitHub App authentication")
        app_jwt = jwt.encode(payload, private_key, algorithm="RS256")

        url = f"https://api.github.com/app/installations/{gh_config.installation_id}/access_tokens"
        jwt_headers = {
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Agno-Knowledge",
        }
        return url, jwt_headers

    @staticmethod
    def _parse_token_response(data: Dict[str, Any]) -> Tuple[str, float]:
        """Extract the installation token and expiry timestamp from the API response."""
        installation_token: str = data["token"]
        expires_at_str = data.get("expires_at", "")
        now = int(time.time())
        if expires_at_str:
            from datetime import datetime

            try:
                expires_at_ts = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00")).timestamp()
            except (ValueError, AttributeError):
                expires_at_ts = float(now + 3600)
        else:
            expires_at_ts = float(now + 3600)
        return installation_token, expires_at_ts

    def _get_github_app_token(self, gh_config: GitHubConfig) -> str:
        """Generate or retrieve a cached installation access token for GitHub App auth.

        Creates a JWT signed with the app's private key, then exchanges it for
        an installation access token via the GitHub API.  Tokens are cached
        until 60 seconds before expiry.

        Uses double-checked locking: the cache is read lock-free first (safe
        under the GIL since dict.get and tuple reads are atomic).  On a cache
        miss the lock is acquired for the full token exchange and cache write,
        preventing duplicate HTTP requests for the same installation.

        Requires ``PyJWT[crypto]``: ``pip install PyJWT cryptography``
        """
        cache_key = f"{gh_config.app_id}:{gh_config.installation_id}"

        # Fast path: lock-free cache read
        cached = self._check_cached_token(self._github_app_token_cache, cache_key)
        if cached is not None:
            return cached

        # Slow path: acquire lock, re-check, then fetch + cache write
        with self._token_cache_lock:
            cached = self._check_cached_token(self._github_app_token_cache, cache_key)
            if cached is not None:
                return cached

            url, jwt_headers = self._build_jwt_and_url(gh_config)

            try:
                with httpx.Client() as client:
                    response = client.post(url, headers=jwt_headers, timeout=30.0)
                    response.raise_for_status()
                    data = response.json()
            except httpx.HTTPStatusError as e:
                log_error(f"GitHub App token exchange failed: {e.response.status_code} {e.response.text}")
                raise
            except httpx.HTTPError as e:
                log_error(f"GitHub App token exchange request failed: {e}")
                raise

            installation_token, expires_at_ts = self._parse_token_response(data)
            self._github_app_token_cache[cache_key] = (installation_token, expires_at_ts)
            return installation_token

    async def _aget_github_app_token(self, gh_config: GitHubConfig) -> str:
        """Generate or retrieve a cached installation access token for GitHub App auth (async).

        Async variant of ``_get_github_app_token``.  Uses ``httpx.AsyncClient``
        so the event loop is not blocked during the token exchange.

        Uses double-checked locking: the cache is read without the async lock
        first (safe because no ``await`` is involved, so no coroutine can
        interleave).  On a cache miss the lock is held for the full token
        exchange and cache write, preventing duplicate HTTP requests.

        Requires ``PyJWT[crypto]``: ``pip install PyJWT cryptography``
        """
        cache_key = f"{gh_config.app_id}:{gh_config.installation_id}"

        # Fast path: lock-free cache read (no await, so no interleaving)
        cached = self._check_cached_token(self._github_app_token_cache, cache_key)
        if cached is not None:
            return cached

        # Ensure the async lock exists (sync lock guards initialization)
        with self._token_cache_lock:
            if self._async_token_cache_lock is None:
                self.__class__._async_token_cache_lock = asyncio.Lock()

        lock = self._async_token_cache_lock
        assert lock is not None

        # Slow path: acquire async lock, re-check, then fetch + cache write
        async with lock:
            cached = self._check_cached_token(self._github_app_token_cache, cache_key)
            if cached is not None:
                return cached

            url, jwt_headers = self._build_jwt_and_url(gh_config)

            try:
                async with AsyncClient() as client:
                    response = await client.post(url, headers=jwt_headers, timeout=30.0)
                    response.raise_for_status()
                    data = response.json()
            except httpx.HTTPStatusError as e:
                log_error(f"GitHub App token exchange failed: {e.response.status_code} {e.response.text}")
                raise
            except httpx.HTTPError as e:
                log_error(f"GitHub App token exchange request failed: {e}")
                raise

            installation_token, expires_at_ts = self._parse_token_response(data)
            self._github_app_token_cache[cache_key] = (installation_token, expires_at_ts)
            return installation_token

    def _validate_github_config(
        self,
        content: Content,
        config: Optional[BaseStorageConfig],
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
        """Build headers for GitHub API requests.

        Uses GitHub App authentication when ``app_id`` is configured,
        otherwise falls back to the personal access token.
        """
        headers: Dict[str, str] = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Agno-Knowledge",
        }
        if gh_config.app_id is not None:
            token = self._get_github_app_token(gh_config)
            headers["Authorization"] = f"Bearer {token}"
        elif gh_config.token:
            headers["Authorization"] = f"Bearer {gh_config.token}"
        return headers

    async def _abuild_github_headers(self, gh_config: GitHubConfig) -> Dict[str, str]:
        """Build headers for GitHub API requests (async).

        Async variant of ``_build_github_headers``.  Uses the async token
        exchange so the event loop is not blocked.
        """
        headers: Dict[str, str] = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Agno-Knowledge",
        }
        if gh_config.app_id is not None:
            token = await self._aget_github_app_token(gh_config)
            headers["Authorization"] = f"Bearer {token}"
        elif gh_config.token:
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
        config: Optional[BaseStorageConfig] = None,
    ):
        """Load content from GitHub (async).

        Requires the GitHub config to contain repo and optionally token for private repos.
        Uses the GitHub API to fetch file contents.
        """
        remote_content: GitHubContent = cast(GitHubContent, content.remote_content)
        gh_config = self._validate_github_config(content, config)
        if gh_config is None:
            return

        headers = await self._abuild_github_headers(gh_config)
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
        config: Optional[BaseStorageConfig] = None,
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
