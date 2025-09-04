# OpenTelemetry Resource Detector for AWS

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-image]

[component owners](https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/.github/component_owners.yml): @jj22ee

Resource detector for Amazon Web Services.

## Status

| Maturity                                  | [Component Owner](../../.github/component_owners.yml) | Compatibility         |
| ----------------------------------------- | ----------------------------------------------------- | --------------------- |
| [Stable](../../CONTRIBUTING.md#stable) | @jj22ee                                               | API 1.0+<br/>SDK 1.0+ |

## Installation

```bash
npm install --save @opentelemetry/resource-detector-aws
```

## Usage

```typescript
import { detectResources } from '@opentelemetry/resources';
import { awsEc2Detector } from '@opentelemetry/resource-detector-aws'
const resource = await detectResources({
   detectors: [awsEc2Detector],
})

const tracerProvider = new NodeTracerProvider({ resource });
```

## Available detectors

This package uses `@opentelemetry/semantic-conventions` version `1.22+`, which implements Semantic Convention [Version 1.7.0](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.7.0/semantic_conventions/README.md)

### AWS Beanstalk Detector

Populates `service` for processes running on [AWS Elastic Beanstalk](https://aws.amazon.com/elasticbeanstalk/)

| Resource Attribute  | Description                                                              |
|---------------------|--------------------------------------------------------------------------|
| cloud.platform      | The cloud platform. In this context, it's always "aws_elastic_beanstalk" |
| cloud.provider      | The cloud provider. In this context, it's always "aws"                   |
| service.instance.id | Value of `deployment_id` from config file `environment.conf`             |
| service.name        | The service name. In this context, it's always "aws_elastic_beanstalk"   |
| service.namespace   | Value of `environment_name` from config file `environment.conf`          |
| service.version     | Value of `version_label` from config file `environment.conf`             |

### AWS EC2 Detector

Populates `cloud` and `host` for processes running on [Amazon EC2](https://aws.amazon.com/ec2/), including abstractions such as ECS on EC2. Notably, it does not populate anything on AWS Fargate.

| Resource Attribute      | Description                                                                           |
|-------------------------|---------------------------------------------------------------------------------------|
| cloud.account.id        | Value of `accountId` from `/latest/dynamic/instance-identity/document` request        |
| cloud.availability_zone | Value of `availabilityZone` from `/latest/dynamic/instance-identity/document` request |
| cloud.platform          | The cloud platform. In this context, it's always "aws_ec2"                            |
| cloud.provider          | The cloud provider. In this context, it's always "aws"                                |
| cloud.region            | Value of `region` from `/latest/dynamic/instance-identity/document` request           |
| host.id                 | Value of `instanceId` from `/latest/dynamic/instance-identity/document` request       |
| host.name               | Value of `hostname` from `/latest/dynamic/instance-identity/document` request         |
| host.type               | Value of `instanceType` from `/latest/dynamic/instance-identity/document` request     |

### AWS ECS Detector

Populates `container` for containers running on [Amazon ECS](https://aws.amazon.com/ecs/).

| Resource Attribute      | Description                                                                            |
|-------------------------|----------------------------------------------------------------------------------------|
| aws.ecs.container.arn   | Value of `ContainerARN` from the request to the metadata Uri. The Metadata Uri is stored on the Environment Variable `ECS_CONTAINER_METADATA_URI_V4`  |
| aws.ecs.cluster.arn     | Value in the format `${baseArn}:cluster/${cluster}`, with `baseArn` and `cluster` from a `ECS_CONTAINER_METADATA_URI_V4/task` request, with values from `TaskARN` and `Cluster` respectively |
| aws.ecs.launchtype      | Value of `LaunchType` from `ECS_CONTAINER_METADATA_URI_V4/task` request                |
| aws.ecs.task.arn        | Value of `TaskARN` from `ECS_CONTAINER_METADATA_URI_V4/task` request                   |
| aws.ecs.task.family     | Value of `Family` from `ECS_CONTAINER_METADATA_URI_V4/task` request                    |
| aws.ecs.task.revision   | Value of `Revision` from `ECS_CONTAINER_METADATA_URI_V4/task` request                  |
| aws.log.group.arns      | Value on format `arn:aws:logs:${logsRegion}:${awsAccount}:log-group:${logsGroupName}`, with `logsRegions` and `logsGroupName` from logs metadata, values of `awslogs-region` and `awslogs-group` respectively, and `awsAccount` parsed value from the `TaskARN`. Logs metadata values come from `LogOptions` on `ECS_CONTAINER_METADATA_URI_V4` request |
| aws.log.group.names     | Value of `awslogs-group` from logs metadata. Logs metadata values come from `LogOptions` on `ECS_CONTAINER_METADATA_URI_V4` request |
| aws.log.stream.arns     | Value on format `arn:aws:logs:${logsRegion}:${awsAccount}:log-group:${logsGroupName}:log-stream:${logsStreamName}`, with `logsRegions`, `logsGroupName` and `logsStreamName` from logs metadata, values of `awslogs-region`, `awslogs-group` and `awslogs-stream` respectively, and `awsAccount` parsed value from the `TaskARN` |
| aws.log.stream.names    | Value of `awslogs-stream` from logs metadata |
| cloud.account.id        | Parsed value from the `TaskARN` |
| cloud.availability_zone | Value of `AvailabilityZone` from `ECS_CONTAINER_METADATA_URI_V4/task` request. This value is not available in all Fargate runtimes |
| cloud.platform          | The cloud platform. In this context, it's always "aws_ecs"                             |
| cloud.provider          | The cloud provider. In this context, it's always "aws"                                 |
| cloud.region            | Parsed value from the `TaskARN`                                                        |
| cloud.resource_id       | Value of `ContainerARN` from `ECS_CONTAINER_METADATA_URI_V4/task` request              |
| container.id            | Value from file `/proc/self/cgroup`                                                    |
| container.name          | The hostname of the operating system                                                   |

### AWS EKS Detector

Populates `container` and `k8s.cluster_name` for containers running on [Amazon EKS](https://aws.amazon.com/eks/).
`k8s.cluster_name` is not always available depending on the configuration of CloudWatch monitoring for the EKS cluster.

| Resource Attribute | Description                                                                                         |
|--------------------|-----------------------------------------------------------------------------------------------------|
| cloud.platform     | The cloud platform. In this context, it's always "aws_eks"                                          |
| cloud.provider     | The cloud provider. In this context, it's always "aws"                                              |
| container.id       | Value from config file `/proc/self/cgroup`                                                          |
| k8s.cluster.name   | Value of `cluster.name` from `/api/v1/namespaces/amazon-cloudwatch/configmaps/cluster-info` request |

### AWS Lambda Detector

Populates `faas` and `cloud` for functions running on [AWS Lambda](https://aws.amazon.com/lambda/).
`faas.id` is currently not populated as it is not provided by the runtime at startup.

| Resource Attribute | Description                                                         |
|--------------------|---------------------------------------------------------------------|
| cloud.platform     | The cloud platform. In this context, it's always "aws_lambda"       |
| cloud.provider     | The cloud provider. In this context, it's always "aws"              |
| cloud.region       | Value of Process Environment Variable `AWS_REGION`                  |
| faas.name          | Value of Process Environment Variable `AWS_LAMBDA_FUNCTION_NAME`    |
| faas.version       | Value of Process Environment Variable `AWS_LAMBDA_FUNCTION_VERSION` |

## Useful links

- For more information on OpenTelemetry, visit: <https://opentelemetry.io/>
- For more about OpenTelemetry JavaScript: <https://github.com/open-telemetry/opentelemetry-js>
- For help or feedback on this project, join us in [GitHub Discussions][discussions-url]

## License

Apache 2.0 - See [LICENSE][license-url] for more information.

[discussions-url]: https://github.com/open-telemetry/opentelemetry-js/discussions
[license-url]: https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/LICENSE
[license-image]: https://img.shields.io/badge/license-Apache_2.0-green.svg?style=flat
[npm-url]: https://www.npmjs.com/package/@opentelemetry/resource-detector-aws
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Fresource-detector-aws.svg
