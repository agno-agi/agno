"""Workflow factory for per-request, context-driven workflow construction."""

from agno.factory import BaseFactory


class WorkflowFactory(BaseFactory):
    """A factory that produces a Workflow per request.

    Factories live alongside workflows in ``AgentOS(workflows=[...])``.
    On each request, AgentOS invokes the factory with a :class:`RequestContext`
    and uses the returned Workflow for that request.
    """

    def _post_resolve(self, component) -> None:
        super()._post_resolve(component)
        component.initialize_workflow()
