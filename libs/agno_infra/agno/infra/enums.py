from enum import Enum


class InfraStarterTemplate(str, Enum):
    agentos_docker = "agentos-docker"
    agentos_aws = "agentos-aws"
    agentos_railway = "agentos-railway"
