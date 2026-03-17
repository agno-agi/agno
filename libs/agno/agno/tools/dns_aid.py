"""DNS-AID tool classes for Agno."""

from agno.tools import Toolkit


class DnsAidDiscoverTool(Toolkit):
    """Toolkit for discovering AI agents via DNS-AID SVCB records."""

    def __init__(self, backend_name: str | None = None, backend=None):
        super().__init__(name="dns_aid_discover")
        self._backend_name = backend_name
        self._backend = backend
        self.register(self.discover_agents)

    def discover_agents(
        self,
        domain: str,
        protocol: str | None = None,
        name: str | None = None,
        require_dnssec: bool = False,
    ) -> str:
        """Discover AI agents at a domain via DNS-AID SVCB records."""
        from dns_aid.integrations import DnsAidOperations

        ops = DnsAidOperations(
            backend_name=self._backend_name, backend=self._backend
        )
        return ops.discover_sync(
            domain=domain,
            protocol=protocol,
            name=name,
            require_dnssec=require_dnssec,
        )


class DnsAidPublishTool(Toolkit):
    """Toolkit for publishing AI agents to DNS via DNS-AID."""

    def __init__(self, backend_name: str | None = None, backend=None):
        super().__init__(name="dns_aid_publish")
        self._backend_name = backend_name
        self._backend = backend
        self.register(self.publish_agent)

    def publish_agent(
        self,
        name: str,
        domain: str,
        protocol: str = "mcp",
        endpoint: str = "",
        port: int = 443,
        capabilities: list[str] | None = None,
        version: str = "1.0.0",
        description: str | None = None,
        ttl: int = 3600,
    ) -> str:
        """Publish an AI agent to DNS via DNS-AID SVCB records."""
        from dns_aid.integrations import DnsAidOperations

        ops = DnsAidOperations(
            backend_name=self._backend_name, backend=self._backend
        )
        return ops.publish_sync(
            name=name,
            domain=domain,
            protocol=protocol,
            endpoint=endpoint,
            port=port,
            capabilities=capabilities,
            version=version,
            description=description,
            ttl=ttl,
        )


class DnsAidUnpublishTool(Toolkit):
    """Toolkit for removing AI agents from DNS via DNS-AID."""

    def __init__(self, backend_name: str | None = None, backend=None):
        super().__init__(name="dns_aid_unpublish")
        self._backend_name = backend_name
        self._backend = backend
        self.register(self.unpublish_agent)

    def unpublish_agent(
        self,
        name: str,
        domain: str,
        protocol: str = "mcp",
    ) -> str:
        """Remove an AI agent from DNS via DNS-AID SVCB records."""
        from dns_aid.integrations import DnsAidOperations

        ops = DnsAidOperations(
            backend_name=self._backend_name, backend=self._backend
        )
        return ops.unpublish_sync(
            name=name,
            domain=domain,
            protocol=protocol,
        )
