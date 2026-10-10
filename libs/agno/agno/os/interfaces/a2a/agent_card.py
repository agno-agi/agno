from typing import Any, Dict, Optional

try:
    from a2a.types import (
        AgentCapabilities,
        AgentCard,
        AgentInterface,
        AgentProvider,
        AgentSkill,
        HTTPAuthSecurityScheme,
        SecurityRequirement,
        SecurityScheme,
        StringList,
    )
except ImportError as e:
    raise ImportError("`a2a` not installed. Please install it with `pip install -U a2a-sdk`") from e


_DEFAULT_CARD_VERSION = "0.0.1"
_PROTOCOL_BINDING = "JSONRPC"
_INPUT_MODES = ["text/plain", "application/json", "image/*", "audio/*", "video/*", "application/octet-stream"]


def build_agent_card(
    entity: Any,
    url: str,
    security_schemes: Optional[Dict[str, SecurityScheme]] = None,
    enable_v0_3_compat: bool = True,
    provider: Optional[AgentProvider] = None,
    documentation_url: Optional[str] = None,
    icon_url: Optional[str] = None,
) -> AgentCard:
    """Build the A2A AgentCard of an Agno Agent, Team or Workflow.

    1. Resolve the identity fields
    2. Build the supported interfaces
    3. Build the skills
    4. Build and return the AgentCard

    Args:
        entity: The Agno Agent, Team or Workflow to describe
        url: The URL the entity's A2A endpoint is served on
        security_schemes: The security schemes a client can authenticate with
        enable_v0_3_compat: Whether the endpoint also serves A2A v0.3 clients
        provider: The organization serving the entity
        documentation_url: The URL of the entity's documentation
        icon_url: The URL of the entity's icon

    Returns:
        AgentCard: The A2A AgentCard
    """

    # 1. Resolve the identity fields
    entity_id = getattr(entity, "id", None) or ""
    entity_name = getattr(entity, "name", None) or entity_id
    # The description is required on the card: an entity without one is described by its name
    entity_description = getattr(entity, "description", None) or entity_name
    entity_version = getattr(entity, "_version", None)

    # 2. Build the supported interfaces
    # The v0.3 interface makes the served card carry the v0.3 fields (url, preferredTransport) too
    supported_interfaces = [AgentInterface(url=url, protocol_binding=_PROTOCOL_BINDING, protocol_version="1.0")]
    if enable_v0_3_compat:
        supported_interfaces.append(AgentInterface(url=url, protocol_binding=_PROTOCOL_BINDING, protocol_version="0.3"))

    # 3. Build the skills
    skill = AgentSkill(
        id=entity_id,
        name=entity_name,
        description=entity_description,
        tags=["agno"],
    )

    # 4. Build and return the AgentCard
    output_modes = ["text/plain"]
    if getattr(entity, "output_schema", None) is not None:
        output_modes = ["application/json", "text/plain"]
    agent_card = AgentCard(
        name=entity_name,
        description=entity_description,
        version=str(entity_version) if entity_version is not None else _DEFAULT_CARD_VERSION,
        supported_interfaces=supported_interfaces,
        capabilities=AgentCapabilities(streaming=True, push_notifications=False, extended_agent_card=False),
        default_input_modes=_INPUT_MODES,
        default_output_modes=output_modes,
        skills=[skill],
    )
    if provider is not None:
        agent_card.provider.CopyFrom(provider)
    if documentation_url:
        agent_card.documentation_url = documentation_url
    if icon_url:
        agent_card.icon_url = icon_url
    if security_schemes:
        for scheme_name, security_scheme in security_schemes.items():
            agent_card.security_schemes[scheme_name].CopyFrom(security_scheme)
            agent_card.security_requirements.append(SecurityRequirement(schemes={scheme_name: StringList()}))
    return agent_card


def build_bearer_security_schemes(bearer_format: Optional[str] = None) -> Dict[str, SecurityScheme]:
    """Build the security schemes of an AgentOS that authenticates requests with a bearer token.

    Args:
        bearer_format: The format of the token, e.g. "JWT". Left out for opaque tokens.

    Returns:
        Dict[str, SecurityScheme]: The security schemes, keyed by scheme name
    """
    http_auth_scheme = HTTPAuthSecurityScheme(scheme="bearer")
    if bearer_format:
        http_auth_scheme.bearer_format = bearer_format
    return {"bearerAuth": SecurityScheme(http_auth_security_scheme=http_auth_scheme)}
