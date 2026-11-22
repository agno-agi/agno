"""A read-only sequence that re-reads its source on every access."""

from typing import Any, Callable, Iterator, List, Sequence


class LiveSequence(Sequence[Any]):
    """A sequence view over a resolver, read at access time.

    Hand one to a toolkit that takes a list of components when the list it should
    see can change after the toolkit is built: a component added to an AgentOS
    later is visible on the next access, with no copy to keep in sync.
    """

    def __init__(self, resolve: Callable[[], List[Any]]):
        self._resolve = resolve

    def __getitem__(self, index):  # type: ignore[no-untyped-def]
        return self._resolve()[index]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._resolve())

    def __len__(self) -> int:
        return len(self._resolve())
