from collections import OrderedDict
from typing import Dict, List, Type, Union

from agno.aws.resource.acm.certificate import AcmCertificate
from agno.aws.resource.base import AwsResource
from agno.aws.resource.cloudformation.stack import CloudFormationStack
from agno.aws.resource.ec2.security_group import SecurityGroup
from agno.aws.resource.ec2.subnet import Subnet
from agno.aws.resource.ec2.volume import EbsVolume
from agno.aws.resource.ecs.cluster import EcsCluster
from agno.aws.resource.ecs.service import EcsService
from agno.aws.resource.ecs.task_definition import EcsTaskDefinition
from agno.aws.resource.elasticache.cluster import CacheCluster
from agno.aws.resource.elasticache.subnet_group import CacheSubnetGroup
from agno.aws.resource.elb.listener import Listener
from agno.aws.resource.elb.load_balancer import LoadBalancer
from agno.aws.resource.elb.target_group import TargetGroup
from agno.aws.resource.emr.cluster import EmrCluster
from agno.aws.resource.glue.crawler import GlueCrawler
from agno.aws.resource.iam.policy import IamPolicy
from agno.aws.resource.iam.role import IamRole
from agno.aws.resource.rds.db_cluster import DbCluster
from agno.aws.resource.rds.db_instance import DbInstance
from agno.aws.resource.rds.db_subnet_group import DbSubnetGroup
from agno.aws.resource.s3.bucket import S3Bucket
from agno.aws.resource.secret.manager import SecretsManager

# Use this as a type for an object which can hold any AwsResource
AwsResourceType = Union[
    AcmCertificate,
    CloudFormationStack,
    EbsVolume,
    IamRole,
    IamPolicy,
    GlueCrawler,
    S3Bucket,
    SecretsManager,
    Subnet,
    SecurityGroup,
    DbSubnetGroup,
    DbCluster,
    DbInstance,
    CacheSubnetGroup,
    CacheCluster,
    EmrCluster,
    EcsCluster,
    EcsTaskDefinition,
    EcsService,
    LoadBalancer,
    TargetGroup,
    Listener,
]

# Use this as an ordered list to iterate over all AwsResource Classes
# This list is the order in which resources should be installed as well.
AwsResourceTypeList: List[Type[AwsResource]] = [
    Subnet,
    SecurityGroup,
    IamRole,
    IamPolicy,
    S3Bucket,
    SecretsManager,
    EbsVolume,
    AcmCertificate,
    CloudFormationStack,
    GlueCrawler,
    DbSubnetGroup,
    DbCluster,
    DbInstance,
    CacheSubnetGroup,
    CacheCluster,
    LoadBalancer,
    TargetGroup,
    Listener,
    EcsCluster,
    EcsTaskDefinition,
    EcsService,
    EmrCluster,
]

# Map Aws resource alias' to their type
_aws_resource_type_names: Dict[str, Type[AwsResource]] = {
    aws_type.__name__.lower(): aws_type for aws_type in AwsResourceTypeList
}
_aws_resource_type_aliases: Dict[str, Type[AwsResource]] = {
    "s3": S3Bucket,
    "volume": EbsVolume,
}

AwsResourceAliasToTypeMap: Dict[str, Type[AwsResource]] = dict(**_aws_resource_type_names, **_aws_resource_type_aliases)

# Maps each AwsResource to an install weight
# lower weight AwsResource(s) get installed first
AwsResourceInstallOrder: Dict[str, int] = OrderedDict(
    {resource_type.__name__: idx for idx, resource_type in enumerate(AwsResourceTypeList, start=1)}
)
