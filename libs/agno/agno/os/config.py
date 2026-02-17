"""Schemas related to the AgentOS configuration"""

from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel, field_validator


class AuthorizationConfig(BaseModel):
    """Configuration for the JWT middleware"""

    verification_keys: Optional[List[str]] = None
    jwks_file: Optional[str] = None
    algorithm: Optional[str] = None
    verify_audience: Optional[bool] = None


class EvalsDomainConfig(BaseModel):
    """Configuration for the Evals domain of the AgentOS"""

    display_name: Optional[str] = None
    available_models: Optional[List[str]] = None


class SessionDomainConfig(BaseModel):
    """Configuration for the Session domain of the AgentOS"""

    display_name: Optional[str] = None


class KnowledgeDomainConfig(BaseModel):
    """Configuration for the Knowledge domain of the AgentOS"""

    display_name: Optional[str] = None


class KnowledgeInstanceConfig(BaseModel):
    """Configuration for a single knowledge instance"""

    id: str
    name: str
    description: Optional[str] = None
    db_id: str
    table: str


class MetricsDomainConfig(BaseModel):
    """Configuration for the Metrics domain of the AgentOS"""

    display_name: Optional[str] = None


class MemoryDomainConfig(BaseModel):
    """Configuration for the Memory domain of the AgentOS"""

    display_name: Optional[str] = None


class TracesDomainConfig(BaseModel):
    """Configuration for the Traces domain of the AgentOS"""

    display_name: Optional[str] = None


DomainConfigType = TypeVar("DomainConfigType")


class DatabaseConfig(BaseModel, Generic[DomainConfigType]):
    """Configuration for a domain when used with the contextual database"""

    db_id: str
    domain_config: Optional[DomainConfigType] = None
    tables: Optional[List[str]] = None


class EvalsConfig(EvalsDomainConfig):
    """Configuration for the Evals domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[EvalsDomainConfig]]] = None


class SessionConfig(SessionDomainConfig):
    """Configuration for the Session domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[SessionDomainConfig]]] = None


class MemoryConfig(MemoryDomainConfig):
    """Configuration for the Memory domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[MemoryDomainConfig]]] = None


class KnowledgeDatabaseConfig(BaseModel):
    """Configuration for a knowledge database with its tables"""

    db_id: str
    domain_config: Optional[KnowledgeDomainConfig] = None
    tables: List[str] = []


class KnowledgeConfig(KnowledgeDomainConfig):
    """Configuration for the Knowledge domain of the AgentOS"""

    dbs: Optional[List[KnowledgeDatabaseConfig]] = None
    knowledge_instances: Optional[List[KnowledgeInstanceConfig]] = None


class MetricsConfig(MetricsDomainConfig):
    """Configuration for the Metrics domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[MetricsDomainConfig]]] = None


class TracesConfig(TracesDomainConfig):
    """Configuration for the Traces domain of the AgentOS"""

    dbs: Optional[List[DatabaseConfig[TracesDomainConfig]]] = None


class ChatConfig(BaseModel):
    """Configuration for the Chat page of the AgentOS"""

    quick_prompts: dict[str, list[str]]

    # Limit the number of quick prompts to 3 (per agent/team/workflow)
    @field_validator("quick_prompts")
    @classmethod
    def limit_lists(cls, v):
        for key, lst in v.items():
            if len(lst) > 3:
                raise ValueError(f"Too many quick prompts for '{key}', maximum allowed is 3")
        return v


class AgentOSConfig(BaseModel):
    """General configuration for an AgentOS instance"""

    available_models: Optional[List[str]] = None
    chat: Optional[ChatConfig] = None
    evals: Optional[EvalsConfig] = None
    knowledge: Optional[KnowledgeConfig] = None
    memory: Optional[MemoryConfig] = None
    session: Optional[SessionConfig] = None
    metrics: Optional[MetricsConfig] = None
    traces: Optional[TracesConfig] = None
