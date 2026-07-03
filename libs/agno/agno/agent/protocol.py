from typing import Any, AsyncIterator, Optional, Protocol, Sequence, Union, runtime_checkable

from agno.media import Audio, File, Image, Video
from agno.run.agent import RunOutput, RunOutputEvent


@runtime_checkable
class AgentProtocol(Protocol):
    """Protocol that any agent must satisfy to be registered with AgentOS.

    This is the minimal contract the agent router requires. Native Agent,
    RemoteAgent, and all external framework adapters must satisfy this.
    """

    @property
    def id(self) -> str: ...

    @property
    def name(self) -> Optional[str]: ...

    # def (not async def) because arun returns either a coroutine or an async iterator.
    def arun(
        self,
        input: Any,
        *,
        stream: Optional[bool] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        images: Optional[Sequence[Image]] = None,
        audio: Optional[Sequence[Audio]] = None,
        videos: Optional[Sequence[Video]] = None,
        files: Optional[Sequence[File]] = None,
        stream_events: Optional[bool] = None,
        **kwargs: Any,
    ) -> Union[RunOutput, AsyncIterator[RunOutputEvent]]: ...
