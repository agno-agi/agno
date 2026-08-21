from dataclasses import dataclass
from os import getenv
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterator, List, Optional, Type, Union

import httpx
from pydantic import BaseModel

from agno.exceptions import ModelAuthenticationError, ModelProviderError
from agno.models.message import Message
from agno.models.openai.open_responses import OpenResponses
from agno.models.response import ModelResponse
from agno.models.xai.oauth import _NO_TOKEN_MESSAGE, XAITokenManager
from agno.run.agent import RunOutput

try:
    from openai import AsyncOpenAI, OpenAI
except ImportError as e:
    raise ImportError("`openai` not installed. Please install using `pip install openai -U`") from e


def _check_openai_version() -> None:
    """SuperGrok OAuth rides on the SDK's callable api_key support, added in 1.106.0."""
    import importlib.metadata

    from packaging.version import parse

    found = importlib.metadata.version("openai")
    if parse(found) < parse("1.106.0"):
        raise ImportError(
            f"SuperGrok OAuth needs openai>=1.106.0 (callable api_key support). "
            f"Found {found}. Please upgrade using `pip install -U openai`."
        )


# The SDK invokes the baked callable on every request, even ones already carrying
# a per-user header, so it must never raise for a merely absent deployment row.
# get_request_params raises instead, with the run's context in hand.
_NOT_SIGNED_IN_SENTINEL = "supergrok-placeholder-not-signed-in"
_NO_MANAGER_FOR_GUARANTEE = (
    "require_user_token=True but no token_manager is configured, so per-user SuperGrok tokens "
    "cannot be resolved. Configure a token_manager, or set require_user_token=False."
)


@dataclass
class xAIResponses(OpenResponses):
    """
    A class for interacting with xAI models using the Responses API.

    Supports two auth modes: an API key (pay-per-token, identical to the chat
    provider) or a SuperGrok subscription via OAuth token providers. In OAuth
    mode the openai SDK receives a callable api_key, so every request carries a
    freshly resolved bearer token. When both are configured, the explicit
    api_key wins (the credential order in _get_client_params).

    Attributes:
        id (str): The model id. Defaults to "grok-4-1-fast-non-reasoning-latest".
        name (str): The model name. Defaults to "xAIResponses".
        provider (str): The provider name. Defaults to "xAI".
        api_key (Optional[str]): The API key. Uses XAI_API_KEY env var if not set.
        base_url (str): The base URL. Defaults to "https://api.x.ai/v1".
        token_provider (Optional[Callable]): Sync callable returning a SuperGrok access token.
        async_token_provider (Optional[Callable]): Async callable returning a SuperGrok access token.
        token_manager (Optional[XAITokenManager]): Derives both providers when neither is set.
        require_user_token (bool): Refuse the shared deployment subscription for an identified
            user who has not signed in. Defaults to False (identified users fall back to it).
        reasoning_replay (bool): Replay encrypted reasoning content across turns. Defaults to False.
    """

    id: str = "grok-4-1-fast-non-reasoning-latest"
    name: str = "xAIResponses"
    provider: str = "xAI"

    api_key: Optional[str] = None
    base_url: str = "https://api.x.ai/v1"

    # xAI's Responses surface is used statelessly; restate the inherited default explicitly
    store: Optional[bool] = False

    token_provider: Optional[Callable[[], str]] = None
    async_token_provider: Optional[Callable[[], Awaitable[str]]] = None
    token_manager: Optional[XAITokenManager] = None

    # A user with no session of their own falls back to the deployment slot;
    # set this to refuse that fallback instead.
    require_user_token: bool = False

    # No role_map override: system messages go to the wire as role "developer",
    # the base class's default map [ASSUMPTION A1].

    # Feature flag for include: ["reasoning.encrypted_content"]; default off
    # because the upstream contract for encrypted reasoning replay is unstable.
    reasoning_replay: bool = False

    def __post_init__(self):
        super().__post_init__()
        # Set the include field up front instead of relying on the base class's
        # request-time auto-merge, which self-extends a caller-provided include list.
        if self._using_reasoning_model():
            include = list(self.include or [])
            if "reasoning.encrypted_content" not in include:
                include.append("reasoning.encrypted_content")
            self.include = include

    def _using_oauth(self) -> bool:
        """OAuth mode: no explicit api_key and a token provider or manager is configured."""
        return self.api_key is None and (
            self.token_provider is not None or self.async_token_provider is not None or self.token_manager is not None
        )

    def _using_reasoning_model(self) -> bool:
        """Reasoning handling applies only when replay is enabled on a reasoning-capable slug."""
        return self.reasoning_replay and self._is_reasoning_slug()

    def _is_reasoning_slug(self) -> bool:
        # The effort/replay-capable slug set from the live catalog [ASSUMPTION A4].
        # "non-reasoning" slugs are explicitly not reasoning-capable, so the
        # substring check must not match them.
        if self.id in {"grok-4.3", "grok-4.5", "grok-4.6"}:
            return True
        return "reasoning" in self.id and "non-reasoning" not in self.id

    def _set_reasoning_request_param(self, base_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Only send a `reasoning` block when the caller explicitly opts in. The base
        class always emits one, and an empty reasoning object is rejected upstream.
        """
        if self.reasoning is None and self.reasoning_effort is None and self.reasoning_summary is None:
            return base_params

        reasoning: Dict[str, Any] = dict(self.reasoning or {})
        if self.reasoning_effort is not None:
            reasoning["effort"] = self.reasoning_effort
        if self.reasoning_summary is not None:
            reasoning["summary"] = self.reasoning_summary

        base_params["reasoning"] = reasoning
        return base_params

    def _get_client_params(self) -> Dict[str, Any]:
        """
        Returns client parameters per the credential order: explicit api_key, then
        token provider / manager (OAuth mode), then the XAI_API_KEY env var.

        In OAuth mode the returned params carry no api_key: the client getters
        insert the right callable for their client type.

        Raises:
            ModelAuthenticationError: If no credential source is configured.
        """
        # Cannot delegate to super()._get_client_params(): the base raises on a
        # missing OPENAI_API_KEY, which is the normal state in OAuth mode.
        if not self.api_key and not self._using_oauth():
            self.api_key = getenv("XAI_API_KEY")
            if not self.api_key:
                raise ModelAuthenticationError(
                    message=(
                        "XAI_API_KEY not set and no SuperGrok token provider configured. Set the XAI_API_KEY "
                        "environment variable, or sign in with SuperGrok and pass token_provider / token_manager."
                    ),
                    model_name=self.name,
                )

        # Build client params
        base_params: Dict[str, Any] = {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "organization": self.organization,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": self.default_headers,
            "default_query": self.default_query,
        }

        # Filter out None values
        client_params = {k: v for k, v in base_params.items() if v is not None}

        # Add additional client params if provided
        if self.client_params:
            client_params.update(self.client_params)

        return client_params

    def _sync_token_callable(self) -> Callable[[], str]:
        """The callable the sync client calls per request; derived from token_manager at build time."""
        if self.token_provider is not None:
            return self.token_provider
        if self.token_manager is not None:
            # Derived here, never in __post_init__: credentials stay plain fields,
            # which keeps deep-copy and dict round-trips correct.
            manager = self.token_manager

            def _deployment_token() -> str:
                try:
                    return manager.get_access_token(user_id="")
                except (ModelAuthenticationError, httpx.HTTPError):
                    return _NOT_SIGNED_IN_SENTINEL

            return _deployment_token
        raise ModelAuthenticationError(
            message=(
                "async_token_provider cannot be used with the sync client: a sync request path cannot "
                "await it (the openai SDK would send the coroutine object as the bearer). "
                "Pass token_provider (sync), or use arun()/aprint_response()."
            ),
            model_name=self.name,
        )

    def _async_token_callable(self) -> Callable[[], Awaitable[str]]:
        """The awaitable callable for the async client; auto-shims a sync-only provider."""
        if self.async_token_provider is not None:
            return self.async_token_provider
        if self.token_manager is not None:
            manager = self.token_manager

            async def _adeployment_token() -> str:
                try:
                    return await manager.aget_access_token(user_id="")
                except (ModelAuthenticationError, httpx.HTTPError):
                    return _NOT_SIGNED_IN_SENTINEL

            return _adeployment_token
        sync_provider = self.token_provider

        async def _shim() -> str:
            return sync_provider()  # type: ignore[misc]

        return _shim

    def get_request_params(
        self,
        messages: Optional[List[Message]] = None,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
    ) -> Dict[str, Any]:
        """Request params, with this run's own SuperGrok bearer when it has one.

        Returns a fresh dict per call and mutates nothing shared, so concurrent
        users on one model instance cannot see each other's credential.
        """
        request_params = super().get_request_params(
            messages=messages,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
        )
        if not self._using_oauth():
            return request_params

        # A4: the guarantee outranks precedence. It decides WHETHER the request may
        # proceed; precedence only decides which credential serves one that may.
        guaranteed = self.require_user_token and bool(self._uid(run_response))
        if guaranteed and self.token_manager is None:
            raise ModelAuthenticationError(message=_NO_MANAGER_FOR_GUARANTEE, model_name=self.name)
        # A1/A2: a provider the caller named is the more specific instruction, and a
        # manager that resolves nothing must not veto a request the provider can serve.
        if not guaranteed and (self.token_provider is not None or self.async_token_provider is not None):
            return request_params
        if self.token_manager is None:
            return request_params

        token = self._per_request_bearer(run_response)
        if token is not None:
            # The SDK merges extra_headers last, over its own auth header, so this
            # overrides the baked credential without copying a client.
            request_params["extra_headers"] = {
                **(request_params.get("extra_headers") or {}),
                "Authorization": f"Bearer {token}",
            }
        return request_params

    def _refresh_slot(self, run_response: Optional[RunOutput]) -> Optional[str]:
        """The slot that served this request, so the retry refreshes that one (§1.3a).

        None when the XAI_API_KEY fallback served it: a 401 then means the key is
        wrong, and no OAuth refresh can fix that. Re-derived rather than stashed
        between request and retry, so nothing shared is written (§1.3a D3); the
        credential was just resolved, so this is a cache hit.
        """
        manager = self.token_manager
        if manager is None:
            return None
        user_id = self._uid(run_response)
        if user_id:
            try:
                manager.get_access_token(user_id=user_id)
                return user_id
            except (ModelAuthenticationError, httpx.HTTPError):
                pass
        try:
            manager.get_access_token(user_id="")
            return ""
        except (ModelAuthenticationError, httpx.HTTPError):
            # No slot could be confirmed - including because the network is down.
            # The caller re-raises the provider's 401, which is what it needs to see.
            return None

    async def _arefresh_slot(self, run_response: Optional[RunOutput]) -> Optional[str]:
        """The slot that served this request, so the retry refreshes that one (§1.3a).

        None when the XAI_API_KEY fallback served it: a 401 then means the key is
        wrong, and no OAuth refresh can fix that. Re-derived rather than stashed
        between request and retry, so nothing shared is written (§1.3a D3); the
        credential was just resolved, so this is a cache hit.
        """
        manager = self.token_manager
        if manager is None:
            return None
        user_id = self._uid(run_response)
        if user_id:
            try:
                await manager.aget_access_token(user_id=user_id)
                return user_id
            except (ModelAuthenticationError, httpx.HTTPError):
                pass
        try:
            await manager.aget_access_token(user_id="")
            return ""
        except (ModelAuthenticationError, httpx.HTTPError):
            # No slot could be confirmed - including because the network is down.
            # The caller re-raises the provider's 401, which is what it needs to see.
            return None

    async def _awarm_credential(self, run_response: Optional[RunOutput]) -> None:
        """Resolve this run's credential on the async path, so assembly is a cache read.

        get_request_params is synchronous and the manager's sync read refuses an
        async db adapter, so without this the row an async backend holds is
        invisible to arun(). Only the cache is populated here: the decisions stay
        in _per_request_bearer, and a failure leaves the cache cold so the
        synchronous path raises exactly what it would have raised anyway.
        """
        if not self._using_oauth() or self.token_manager is None:
            return
        user_id = self._uid(run_response)
        candidates = [user_id] if user_id else []
        if not (user_id and self.require_user_token):
            candidates.append("")
        for candidate in candidates:
            try:
                await self.token_manager.aget_access_token(user_id=candidate)
                return
            except ModelAuthenticationError as e:
                # A failed refresh is not an absent row. Only this coroutine can
                # tell them apart: the sync resolver that runs next cannot read an
                # async store, so it would read the failure as absence and fall
                # through to the shared slot (§1.2 step 2).
                if candidate and e.message != _NO_TOKEN_MESSAGE:
                    raise
            except httpx.HTTPError:
                # Not swallowed for the deployment slot either: the sync resolver
                # would repeat the same call on the event loop, and it cannot reach
                # the env fallback through a transport error anyway.
                raise

    @staticmethod
    def _uid(run_response: Optional[RunOutput]) -> str:
        """The run's user, or the empty deployment slot for script and unidentified runs."""
        return (run_response.user_id if run_response is not None else None) or ""

    def _per_request_bearer(self, run_response: Optional[RunOutput]) -> Optional[str]:
        """This run's own SuperGrok token, or None when the deployment slot serves it.

        Resolution happens here rather than in the baked callable so the
        no-credential error carries the run's context and is raised before the
        SDK is ever called. This is synchronous on both paths; the async legs
        await _awarm_credential first, so the lookup here is a cache hit rather
        than a blocking db read on the event loop.
        """
        manager = self.token_manager
        if manager is None:
            return None
        user_id = self._uid(run_response)
        if user_id:
            try:
                return manager.get_access_token(user_id=user_id)
            except ModelAuthenticationError as e:
                # Only an ABSENT row falls through (§1.2 step 2). A refresh that
                # failed is not absence: the user has a credential, and quietly
                # spending the shared one would bill the wrong subscription.
                if e.message != _NO_TOKEN_MESSAGE:
                    raise
                if self.require_user_token:
                    raise ModelAuthenticationError(
                        message=(
                            f"No SuperGrok sign-in found for user '{user_id}' and this deployment "
                            "requires per-user tokens (require_user_token=True). Ask the user to "
                            "sign in with SuperGrok first."
                        ),
                        model_name=self.name,
                    ) from e
        # The deployment slot serves this run; resolving it here raises the
        # no-credential error that the sentinel callable deliberately swallows.
        try:
            manager.get_access_token(user_id="")
        except ModelAuthenticationError:
            # §1.2 step 3: the chain continues to the environment before giving up
            env_key = getenv("XAI_API_KEY")
            if not env_key:
                raise
            return env_key
        return None

    def get_client(self) -> OpenAI:
        """
        Returns an OpenAI client. Caches the client to avoid recreating it on every request.

        Returns:
            OpenAI: An instance of the OpenAI client.
        """
        if self.client and not self.client.is_closed():
            return self.client

        client_params: Dict[str, Any] = self._get_client_params()
        if self._using_oauth():
            _check_openai_version()
            client_params["api_key"] = self._sync_token_callable()
        if self.http_client is not None:
            client_params["http_client"] = self.http_client
        # When no custom http_client is provided, let the OpenAI SDK use its own default client.
        # The SDK defaults to HTTP/1.1 which avoids transient 400 errors caused by HTTP/2
        # protocol edge cases with OpenAI's infrastructure.

        self.client = OpenAI(**client_params)
        return self.client

    def get_async_client(self) -> AsyncOpenAI:
        """
        Returns an asynchronous OpenAI client. Caches the client to avoid recreating it on every request.

        Returns:
            AsyncOpenAI: An instance of the asynchronous OpenAI client.
        """
        if self.async_client and not self.async_client.is_closed():
            return self.async_client

        client_params: Dict[str, Any] = self._get_client_params()
        if self._using_oauth():
            _check_openai_version()
            client_params["api_key"] = self._async_token_callable()
        if self.http_client and isinstance(self.http_client, httpx.AsyncClient):
            client_params["http_client"] = self.http_client
        # When no custom http_client is provided, let the OpenAI SDK use its own default client.
        # The SDK defaults to HTTP/1.1 which avoids transient 400 errors caused by HTTP/2
        # protocol edge cases with OpenAI's infrastructure.

        self.async_client = AsyncOpenAI(**client_params)
        return self.async_client

    def _decorated_403(self, exc: ModelProviderError) -> ModelProviderError:
        """The 403 rewritten with SuperGrok subscription guidance; same class, same status."""
        return ModelProviderError(
            message=(
                "xAI rejected this request (403). When signed in with SuperGrok this usually means "
                "the subscription tier does not include this model or API access, the subscription "
                "is inactive, or its quota is exhausted — note X Premium does not include xAI API "
                "access. Retrying or re-logging-in will not help. To use pay-per-token access "
                f"instead, set XAI_API_KEY. Provider message: {exc.message}"
            ),
            status_code=403,
            model_name=self.name,
            model_id=self.id,
        )

    def _should_decorate_403(self, exc: ModelProviderError) -> bool:
        """OAuth-mode 403s get subscription guidance; API-key mode passes through untouched."""
        return self._using_oauth() and exc.status_code == 403

    def _should_retry_401(self, exc: ModelProviderError, explicit_provider: Optional[Callable]) -> bool:
        """The 401 one-shot leg applies when the manager actually feeds the failing client [A2].

        An explicit provider wins over the manager in both the callable and request
        assembly (§1.2c A1), so refreshing the manager would not change the bearer
        the retry sends - the caller passes the provider field its client type
        resolves first. The one exception is a require_user_token run, where the
        guarantee outranks precedence and a per-user 401 is meant to surface.
        """
        return (
            self._using_oauth()
            and exc.status_code == 401
            and self.token_manager is not None
            and explicit_provider is None
        )

    def invoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> ModelResponse:
        """
        Send a request to the xAI Responses API, decorating SuperGrok auth errors.
        """
        call_kwargs: Dict[str, Any] = dict(
            messages=messages,
            assistant_message=assistant_message,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
            compress_tool_results=compress_tool_results,
        )
        try:
            return super().invoke(**call_kwargs)
        except ModelProviderError as exc:
            if self._should_decorate_403(exc):
                raise self._decorated_403(exc) from exc
            if not self._should_retry_401(exc, self.token_provider):
                raise
            # One-shot 401 recovery: refresh, rebuild the client, retry exactly once
            slot = self._refresh_slot(run_response)
            if slot is None:
                raise  # the env key served this request; no OAuth refresh helps (§1.3a D2)
            self.token_manager.force_refresh(user_id=slot)  # type: ignore[union-attr]
            self.client = None  # the rebuild re-inserts the token callable
            try:
                return super().invoke(**call_kwargs)
            except ModelProviderError as retry_exc:
                if self._should_decorate_403(retry_exc):
                    raise self._decorated_403(retry_exc) from retry_exc
                raise

    async def ainvoke(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> ModelResponse:
        """
        Sends an asynchronous request to the xAI Responses API, decorating SuperGrok auth errors.
        """
        call_kwargs: Dict[str, Any] = dict(
            messages=messages,
            assistant_message=assistant_message,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
            compress_tool_results=compress_tool_results,
        )
        await self._awarm_credential(run_response)
        try:
            return await super().ainvoke(**call_kwargs)
        except ModelProviderError as exc:
            if self._should_decorate_403(exc):
                raise self._decorated_403(exc) from exc
            if not self._should_retry_401(exc, self.async_token_provider):
                raise
            # One-shot 401 recovery: refresh, rebuild the client, retry exactly once
            slot = await self._arefresh_slot(run_response)
            if slot is None:
                raise  # the env key served this request; no OAuth refresh helps (§1.3a D2)
            await self.token_manager.aforce_refresh(user_id=slot)  # type: ignore[union-attr]
            self.async_client = None  # the rebuild re-inserts the token callable
            try:
                return await super().ainvoke(**call_kwargs)
            except ModelProviderError as retry_exc:
                if self._should_decorate_403(retry_exc):
                    raise self._decorated_403(retry_exc) from retry_exc
                raise

    def invoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> Iterator[ModelResponse]:
        """
        Send a streaming request to the xAI Responses API, decorating SuperGrok auth errors.
        """
        call_kwargs: Dict[str, Any] = dict(
            messages=messages,
            assistant_message=assistant_message,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
            compress_tool_results=compress_tool_results,
        )
        yielded_anything = False
        try:
            for chunk in super().invoke_stream(**call_kwargs):
                yielded_anything = True
                yield chunk
            return
        except ModelProviderError as exc:
            if self._should_decorate_403(exc):
                raise self._decorated_403(exc) from exc
            # Retry only if nothing was yielded yet: deltas must not replay
            if yielded_anything or not self._should_retry_401(exc, self.token_provider):
                raise
            auth_error = exc
        slot = self._refresh_slot(run_response)
        if slot is None:
            # The env key served this request; no OAuth refresh helps (§1.3a D2).
            # Named, not a bare raise: out here the except block has already
            # unbound exc, and a bare raise would be a RuntimeError.
            raise auth_error
        self.token_manager.force_refresh(user_id=slot)  # type: ignore[union-attr]
        self.client = None  # the rebuild re-inserts the token callable
        try:
            yield from super().invoke_stream(**call_kwargs)
        except ModelProviderError as retry_exc:
            if self._should_decorate_403(retry_exc):
                raise self._decorated_403(retry_exc) from retry_exc
            raise

    async def ainvoke_stream(
        self,
        messages: List[Message],
        assistant_message: Message,
        response_format: Optional[Union[Dict, Type[BaseModel]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Union[str, Dict[str, Any]]] = None,
        run_response: Optional[RunOutput] = None,
        compress_tool_results: bool = False,
    ) -> AsyncIterator[ModelResponse]:
        """
        Sends an asynchronous streaming request to the xAI Responses API, decorating SuperGrok auth errors.
        """
        call_kwargs: Dict[str, Any] = dict(
            messages=messages,
            assistant_message=assistant_message,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
            compress_tool_results=compress_tool_results,
        )
        await self._awarm_credential(run_response)
        yielded_anything = False
        try:
            async for chunk in super().ainvoke_stream(**call_kwargs):
                yielded_anything = True
                yield chunk
            return
        except ModelProviderError as exc:
            if self._should_decorate_403(exc):
                raise self._decorated_403(exc) from exc
            # Retry only if nothing was yielded yet: deltas must not replay
            if yielded_anything or not self._should_retry_401(exc, self.async_token_provider):
                raise
            auth_error = exc
        slot = await self._arefresh_slot(run_response)
        if slot is None:
            # The env key served this request; no OAuth refresh helps (§1.3a D2).
            # Named, not a bare raise: out here the except block has already
            # unbound exc, and a bare raise would be a RuntimeError.
            raise auth_error
        await self.token_manager.aforce_refresh(user_id=slot)  # type: ignore[union-attr]
        self.async_client = None  # the rebuild re-inserts the token callable
        try:
            async for chunk in super().ainvoke_stream(**call_kwargs):
                yield chunk
        except ModelProviderError as retry_exc:
            if self._should_decorate_403(retry_exc):
                raise self._decorated_403(retry_exc) from retry_exc
            raise
