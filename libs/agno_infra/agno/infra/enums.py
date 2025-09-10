from enum import Enum


class InfraStarterTemplate(str, Enum):
    agent_infra_docker = "agent-infra-docker"
    agent_infra_aws = "agent-infra-aws"
