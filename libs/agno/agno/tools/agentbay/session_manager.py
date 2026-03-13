"""
AgentBay Session Manager.

Global singleton manager for AgentBay session lifecycle.
Design reference: agentbay-infra-runtime SandboxManager.
"""

import asyncio
import os
from typing import Any, Dict, List, Optional, Set

from agno.utils.log import log_debug, log_error, log_info, log_warning

try:
    from agentbay import AsyncAgentBay, ContextSync, CreateSessionParams
except ImportError:
    raise ImportError("`agentbay` not installed. Please install using `pip install wuying-agentbay-sdk`")


class AgentBaySessionManager:
    """
    全局单例管理器，管理所有 AgentBay Session。

    特性：
    - 单例模式，确保全局只有一个管理器实例
    - 支持 Context Manager，自动清理资源
    - 跨实例 Session 复用
    - 统一的创建、获取、清理接口
    """

    _instance: Optional["AgentBaySessionManager"] = None
    _initialized: bool = False

    def __new__(cls, api_key: Optional[str] = None) -> "AgentBaySessionManager":
        """
        创建单例实例。

        Args:
            api_key: AgentBay API key. If None, will try to get from environment.

        Returns:
            The singleton AgentBaySessionManager instance.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, api_key: Optional[str] = None) -> None:
        """
        初始化 SessionManager 单例。

        Args:
            api_key: AgentBay API key. If None, will try to get from environment.
        """
        # Only initialize once
        if AgentBaySessionManager._initialized:
            return

        self.api_key = api_key or os.getenv("AGENTBAY_API_KEY")
        if not self.api_key:
            raise ValueError(
                "AgentBay API key is required. Set AGENTBAY_API_KEY environment variable or pass api_key parameter."
            )

        # AgentBay client instance, initialized lazily in start()
        self.agent_bay: Optional[AsyncAgentBay] = None

        # Set to store unique environment types
        self._environments: Set[str] = set()

        # Cache for session instances by session_key
        # Format: {environment: {session_key: session_id}}
        self._session_cache: Dict[str, Dict[str, str]] = {}

        # Cache for session objects by session_id (for reuse)
        self._session_objects: Dict[str, Any] = {}

        AgentBaySessionManager._initialized = True

    async def start(self, api_key: Optional[str] = None) -> None:
        """
        初始化 AgentBay 客户端。

        This method is separated from __init__ to allow explicit control of
        when the AgentBay client is initialized.

        Args:
            api_key: Optional API key to update.
        """
        # Update api_key if provided explicitly when starting
        if api_key is not None:
            self.api_key = api_key

        # Ensure we have an API key before initializing client
        if not self.api_key:
            raise ValueError(
                "AgentBay API key is required. Set AGENTBAY_API_KEY "
                "environment variable or pass api_key parameter to start()."
            )

        # If already started, do nothing
        if self.agent_bay is not None:
            return

        try:
            self.agent_bay = AsyncAgentBay(api_key=self.api_key)
            log_info("AgentBay client initialized successfully")
        except ImportError as e:
            raise ImportError(
                "AgentBay SDK is not installed. Please install it with: pip install wuying-agentbay-sdk",
            ) from e
        except (ValueError, TypeError, RuntimeError, AttributeError) as e:
            raise RuntimeError(
                f"Failed to initialize AgentBay client: {e}",
            ) from e

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        """Async context manager exit - automatically cleanup."""
        await self.cleanup()

    def __enter__(self):
        """Sync context manager entry (for compatibility)."""
        # For sync usage, we need to ensure event loop exists
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                log_warning("Event loop is already running. Use async context manager instead.")
            else:
                loop.run_until_complete(self.start())
        except RuntimeError:
            # No event loop, create one
            asyncio.run(self.start())
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Sync context manager exit - automatically cleanup."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is running, schedule cleanup
                asyncio.create_task(self.cleanup())
            else:
                loop.run_until_complete(self.cleanup())
        except RuntimeError:
            asyncio.run(self.cleanup())

    async def cleanup(self) -> None:
        """
        清理所有管理的 Session 并清空内部缓存。

        Deletes all managed session instances and clears the internal dictionaries.
        """
        log_info("Cleaning up all AgentBay sessions...")
        cleaned_count = 0
        failed_count = 0

        # 如果 agent_bay 未初始化，先初始化它
        if not self.agent_bay:
            try:
                await self.start()
            except Exception as e:
                log_warning(f"Failed to start agent_bay for cleanup: {e}")
                # 即使启动失败，也要清空缓存
                self._session_cache.clear()
                self._session_objects.clear()
                self._environments.clear()
                log_info("Cleared session cache (agent_bay not initialized)")
                return

        if self.agent_bay is None:
            return

        # Clean up all cached sessions
        for env, sessions in list(self._session_cache.items()):
            for session_key, session_id in list(sessions.items()):
                try:
                    # 优先使用缓存的 session 对象
                    if session_id in self._session_objects:
                        session = self._session_objects[session_id]
                        try:
                            delete_result = await session.delete()
                            if delete_result.success:
                                cleaned_count += 1
                                log_info(f"Deleted session: {session_id}")
                            else:
                                failed_count += 1
                                error_msg = getattr(delete_result, "error_message", "Unknown error")
                                log_warning(f"Failed to delete session {session_id}: {error_msg}")
                        except Exception as e:
                            failed_count += 1
                            log_warning(f"Exception deleting session {session_id}: {e}")
                    else:
                        # 如果没有缓存的 session 对象，使用 get() 方法获取 Session 对象
                        # get() 返回 SessionResult (有 session 属性)
                        # get_session() 返回 GetSessionResult (没有 session 属性)
                        result = await self.agent_bay.get(session_id)
                        if result.success and result.session:
                            delete_result = await result.session.delete()
                            if delete_result.success:
                                cleaned_count += 1
                                log_info(f"Deleted session: {session_id}")
                            else:
                                failed_count += 1
                                error_msg = getattr(delete_result, "error_message", "Unknown error")
                                log_warning(f"Failed to delete session {session_id}: {error_msg}")
                        else:
                            failed_count += 1
                            error_msg = getattr(result, "error_message", "Unknown error")
                            log_warning(f"Failed to get session {session_id}: {error_msg}")
                except Exception as e:
                    failed_count += 1
                    log_warning(f"Exception processing session {session_id}: {e}")
                finally:
                    # Always remove from cache, even if deletion failed
                    if session_key in sessions:
                        del sessions[session_key]
                    if session_id in self._session_objects:
                        del self._session_objects[session_id]

        # Clear all caches
        self._session_cache.clear()
        self._session_objects.clear()
        self._environments.clear()

        log_info(f"Cleanup completed: {cleaned_count} sessions deleted, {failed_count} failed")

    def _build_session_key(
        self, environment: str, context_id: Optional[str] = None, mount_path: Optional[str] = None
    ) -> str:
        """
        构建 session key。

        Args:
            environment: Environment type (e.g., browser_latest, linux_latest)
            context_id: Optional context ID
            mount_path: Optional mount path

        Returns:
            Session key string
        """
        if context_id:
            if not mount_path:
                raise ValueError("mount_path is required when context_id is provided")
            return f"agbsession_{environment}_ctx_{context_id}_{mount_path}"
        else:
            return f"agbsession_{environment}"

    async def get_or_create_session(
        self,
        environment: str,
        context_id: Optional[str] = None,
        mount_path: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None,
    ):
        """
        获取或创建 Session。

        如果缓存中存在有效的 session，则复用；否则创建新的 session。

        Args:
            environment: Environment type (e.g., browser_latest, linux_latest)
            context_id: Optional context ID to mount
            mount_path: Optional mount path for context (required if context_id is provided)
            labels: Optional labels for the session

        Returns:
            AgentBay Session object
        """
        if not self.agent_bay:
            await self.start()
        if self.agent_bay is None:
            raise RuntimeError("AgentBay client not initialized")

        session_key = self._build_session_key(environment, context_id, mount_path)

        # Check cache first
        if environment in self._session_cache:
            cached_session_id = self._session_cache[environment].get(session_key)
            if cached_session_id:
                # 优先使用缓存的 session 对象
                if cached_session_id in self._session_objects:
                    session = self._session_objects[cached_session_id]
                    try:
                        # 验证 session 是否仍然有效
                        info_result = await session.info()
                        if info_result.success:
                            log_debug(f"Reusing cached session: {cached_session_id}")
                            return session
                    except Exception as e:
                        log_debug(f"Session {cached_session_id} info check failed: {e}, will remove from cache")

                # 如果缓存对象无效，使用 get() 方法获取 Session 对象
                # get() 返回 SessionResult (有 session 属性)
                # get_session() 返回 GetSessionResult (没有 session 属性)
                try:
                    result = await self.agent_bay.get(cached_session_id)
                    if result.success and result.session:
                        try:
                            info_result = await result.session.info()
                            if info_result.success:
                                log_debug(f"Reusing cached session: {cached_session_id}")
                                # 更新缓存
                                self._session_objects[cached_session_id] = result.session
                                return result.session
                        except Exception as e:
                            log_debug(f"Session {cached_session_id} info check failed: {e}")

                    # Session 无效，从缓存中移除
                    log_debug(f"Session {cached_session_id} is invalid, removing from cache")
                    del self._session_cache[environment][session_key]
                    if cached_session_id in self._session_objects:
                        del self._session_objects[cached_session_id]
                except Exception as e:
                    log_debug(f"Failed to get cached session {cached_session_id}: {e}, removing from cache")
                    if session_key in self._session_cache[environment]:
                        del self._session_cache[environment][session_key]
                    if cached_session_id in self._session_objects:
                        del self._session_objects[cached_session_id]

        # Create new session
        return await self.create_session(
            environment=environment, context_id=context_id, mount_path=mount_path, labels=labels
        )

    async def create_session(
        self,
        environment: str,
        context_id: Optional[str] = None,
        mount_path: Optional[str] = None,
        labels: Optional[Dict[str, str]] = None,
    ):
        """
        创建新的 Session。

        Args:
            environment: Environment type (e.g., browser_latest, linux_latest)
            context_id: Optional context ID to mount
            mount_path: Optional mount path for context (required if context_id is provided)
            labels: Optional labels for the session

        Returns:
            AgentBay Session object
        """
        if not self.agent_bay:
            await self.start()
        if self.agent_bay is None:
            raise RuntimeError("AgentBay client not initialized")

        # Validate context parameters
        if context_id and not mount_path:
            raise ValueError("mount_path is required when context_id is provided")

        # Build session parameters
        session_labels = labels.copy() if labels else {}
        session_labels.setdefault("created_by", "agno_agentbay_toolkit")
        session_labels.setdefault("environment", environment)

        # Create session params with or without context_syncs
        if context_id:
            params = CreateSessionParams(
                image_id=environment,
                context_syncs=[ContextSync(context_id=context_id, path=mount_path)],
                labels=session_labels,
            )
            log_info(f"Creating session with context: {context_id} at {mount_path}")
        else:
            params = CreateSessionParams(image_id=environment, labels=session_labels)
            log_info("Creating session without context")

        # Create session
        result = await self.agent_bay.create(params)

        if not result.success or not result.session:
            error_msg = getattr(result, "error_message", "Unknown error")
            raise Exception(f"Failed to create session: {error_msg}")

        session = result.session
        session_id = session.session_id

        # Cache session
        session_key = self._build_session_key(environment, context_id, mount_path)
        if environment not in self._session_cache:
            self._session_cache[environment] = {}
        self._session_cache[environment][session_key] = session_id
        self._session_objects[session_id] = session
        self._environments.add(environment)

        log_info(f"Created new AgentBay session: {session_id} (environment: {environment})")

        return session

    async def get_session(self, session_id: str):
        """
        根据 session_id 获取 Session。

        Args:
            session_id: Session ID to retrieve

        Returns:
            AgentBay Session object if found and valid, None otherwise
        """
        if not self.agent_bay:
            await self.start()
        if self.agent_bay is None:
            raise RuntimeError("AgentBay client not initialized")

        # Check cache first
        if session_id in self._session_objects:
            return self._session_objects[session_id]

        # Get from AgentBay using get() method (not get_session())
        # get() 返回 SessionResult (有 session 属性)
        # get_session() 返回 GetSessionResult (没有 session 属性)
        try:
            result = await self.agent_bay.get(session_id)
            if result.success and result.session:
                # Cache for future use
                self._session_objects[session_id] = result.session
                return result.session
            else:
                error_msg = getattr(result, "error_message", "Unknown error")
                log_warning(f"Session {session_id} not found or invalid: {error_msg}")
                return None
        except Exception as e:
            log_error(f"Error getting session {session_id}: {e}")
            return None

    async def list_sessions(self, environment: Optional[str] = None) -> List[str]:
        """
        列出所有 Session ID。

        Args:
            environment: Optional environment to filter by

        Returns:
            List of session IDs
        """
        if not self.agent_bay:
            await self.start()
        if self.agent_bay is None:
            raise RuntimeError("AgentBay client not initialized")

        try:
            result = await self.agent_bay.list()
            if result.success and result.session_ids:
                if environment:
                    # Filter by environment (would need to check each session's labels)
                    # For now, return all and let caller filter
                    return result.session_ids
                return result.session_ids
            return []
        except Exception as e:
            log_error(f"Error listing sessions: {e}")
            return []

    async def delete_session(self, session_id: str, sync_context: bool = False) -> bool:
        """
        删除指定的 Session。

        Args:
            session_id: Session ID to delete
            sync_context: Whether to sync context before deleting

        Returns:
            True if deletion was successful, False otherwise
        """
        if not self.agent_bay:
            await self.start()
        if self.agent_bay is None:
            raise RuntimeError("AgentBay client not initialized")

        try:
            # 优先使用缓存的 session 对象
            if session_id in self._session_objects:
                session = self._session_objects[session_id]
                delete_result = await session.delete(sync_context=sync_context)
                if delete_result.success:
                    # Remove from caches
                    for env, sessions in list(self._session_cache.items()):
                        for key, sid in list(sessions.items()):
                            if sid == session_id:
                                del sessions[key]
                    if session_id in self._session_objects:
                        del self._session_objects[session_id]
                    log_info(f"Deleted session: {session_id}")
                    return True
                else:
                    error_msg = getattr(delete_result, "error_message", "Unknown error")
                    log_warning(f"Failed to delete session {session_id}: {error_msg}")
                    return False
            else:
                # 如果没有缓存的 session 对象，使用 get() 方法获取
                # get() 返回 SessionResult (有 session 属性)
                result = await self.agent_bay.get(session_id)
                if result.success and result.session:
                    delete_result = await result.session.delete(sync_context=sync_context)
                    if delete_result.success:
                        # Remove from caches
                        for env, sessions in list(self._session_cache.items()):
                            for key, sid in list(sessions.items()):
                                if sid == session_id:
                                    del sessions[key]
                        if session_id in self._session_objects:
                            del self._session_objects[session_id]
                        log_info(f"Deleted session: {session_id}")
                        return True
                    else:
                        error_msg = getattr(delete_result, "error_message", "Unknown error")
                        log_warning(f"Failed to delete session {session_id}: {error_msg}")
                        return False
                else:
                    error_msg = getattr(result, "error_message", "Unknown error")
                    log_warning(f"Session {session_id} not found: {error_msg}")
                    return False
        except Exception as e:
            log_error(f"Error deleting session {session_id}: {e}")
            return False

    def get_cached_sessions(self) -> Dict[str, Dict[str, str]]:
        """
        获取所有缓存的 Session。

        Returns:
            Dictionary mapping environment to session_key to session_id
        """
        return self._session_cache.copy()
