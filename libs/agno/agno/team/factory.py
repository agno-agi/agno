"""Team factory for per-request, context-driven team construction."""

from agno.factory import BaseFactory


class TeamFactory(BaseFactory):
    """A factory that produces a Team per request.

    Factories live alongside teams in ``AgentOS(teams=[...])``.
    On each request, AgentOS invokes the factory with a :class:`RequestContext`
    and uses the returned Team for that request.
    """

    def _post_resolve(self, component) -> None:
        super()._post_resolve(component)
        component.initialize_team()
