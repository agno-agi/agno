from enum import Enum


class InfraStarterTemplate(str, Enum):
    agentos_docker_template = "agentos-docker-template"
    agentos_aws_template = "agentos-aws-template"
    agentos_railway_template = "agentos-railway-template"
