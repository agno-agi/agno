# OpenTelemetry aws-sdk Instrumentation for Node.js

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-image]

[component owners](https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/.github/component_owners.yml): @blumamir @jj22ee @trivikr

This module provides automatic instrumentation for the [AWS SDK for JavaScript v3](https://github.com/aws/aws-sdk-js-v3) modules, which may be loaded using the [`@opentelemetry/sdk-trace-node`](https://github.com/open-telemetry/opentelemetry-js/tree/main/packages/opentelemetry-sdk-trace-node) package and is included in the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle.

If total installation size is not constrained, it is recommended to use the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle with [@opentelemetry/sdk-node](`https://www.npmjs.com/package/@opentelemetry/sdk-node`) for the most seamless instrumentation experience.

Compatible with OpenTelemetry JS API and SDK `1.0+`.

## Installation

```bash
npm install --save @opentelemetry/instrumentation-aws-sdk
```

## Supported Versions

- `@aws-sdk/client-*` versions `>=3.0.0 <4`

## Usage

For further automatic instrumentation instruction see the [@opentelemetry/instrumentation](https://www.npmjs.com/package/@opentelemetry/instrumentation) package.

```js
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const { registerInstrumentations } = require('@opentelemetry/instrumentation');
const {
  AwsInstrumentation,
} = require('@opentelemetry/instrumentation-aws-sdk');

const provider = new NodeTracerProvider();
provider.register();

registerInstrumentations({
  instrumentations: [
    new AwsInstrumentation({
      // see under for available configuration
    }),
  ],
});
```

### aws-sdk Instrumentation Options

aws-sdk instrumentation has few options available to choose from. You can set the following:

| Options                                   | Type                                      | Description                                                                                                                                                                     |
| ----------------------------------------- | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `preRequestHook`                          | `AwsSdkRequestCustomAttributeFunction`    | Hook called before request send, which allow to add custom attributes to span.                                                                                                  |
| `responseHook`                            | `AwsSdkResponseCustomAttributeFunction`   | Hook for adding custom attributes when response is received from aws.                                                                                                           |
| `exceptionHook`                           | `AwsSdkExceptionCustomAttributeFunction`  | Hook for adding custom attributes when exception is received from aws.                                                                                                          |
| `suppressInternalInstrumentation`         | `boolean`                                 | Most aws operation use http requests under the hood. Set this to `true` to hide all underlying http spans.                                                                      |
| `sqsExtractContextPropagationFromPayload` | `boolean`                                 | Will parse and extract context propagation headers from SQS Payload, false by default. [When should it be used?](./doc/sns.md#integration-with-sqs)                             |
| `dynamoDBStatementSerializer`             | `AwsSdkDynamoDBStatementSerializer`       | AWS SDK instrumentation will serialize DynamoDB commands to the `db.statement` attribute using the specified function. Defaults to using a serializer that returns `undefined`. |

## Span Attributes

The instrumentations are collecting the following attributes:
| Attribute Name | Type | Description | Example |
| -------------- | ---- | ----------- | ------- |
| `rpc.system` | string | Always equals "aws-api" | |
| `rpc.method` | string | he name of the operation corresponding to the request, as returned by the AWS SDK. If the SDK does not provide a way to retrieve a name, the name of the command SHOULD be used, removing the suffix `Command` if present, resulting in a PascalCase name with no spaces. | `PutObject` |
| `rpc.service` | string | The name of the service to which a request is made, as returned by the AWS SDK. If the SDK does not provide a away to retrieve a name, the name of the SDK's client interface for a service SHOULD be used, removing the suffix `Client` if present, resulting in a PascalCase name with no spaces. | `S3`, `DynamoDB`, `Route53` |
| `cloud.region` | string | Region name for the request | "eu-west-1" |

### Custom User Attributes

The instrumentation user can configure a `preRequestHook` function which will be called before each request, with a normalized request object and the corresponding span.
This hook can be used to add custom attributes to the span with any logic.
For example, user can add interesting attributes from the `request.params`, and write custom logic based on the service and operation.
Usage example:

```js
awsInstrumentationConfig = {
  preRequestHook: (span, request) => {
    if (span.serviceName === 's3') {
      span.setAttribute('s3.bucket.name', request.commandInput['Bucket']);
    }
  },
};
```

### Specific Service Logic

AWS contains dozens of services accessible with the JS SDK. For many services, the default attributes specified above are enough, but other services have specific [trace semantic conventions](https://github.com/open-telemetry/opentelemetry-specification/tree/master/specification/trace/semantic_conventions), or need to inject/extract intra-process context, or set intra-process context correctly.

Specific service logic currently implemented for:

- [SQS](./doc/sqs.md)
- [SNS](./doc/sns.md)
- [Lambda](./doc/lambda.md)
- DynamoDb
- Amazon Bedrock Runtime (See the [GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/).)

## Potential Side Effects

The instrumentation is doing best effort to support the trace specification of OpenTelemetry. For SQS, it involves defining new attributes on the `Messages` array, as well as on the manipulated types generated from this array (to set correct trace context for a single SQS message operation). Those properties are defined as [non-enumerable](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Enumerability_and_ownership_of_properties) properties, so they have minimum side effect on the app. They will, however, show when using the `Object.getOwnPropertyDescriptors` and `Reflect.ownKeys` functions on SQS `Messages` array and for each `Message` in the array.

## Semantic Conventions

This package uses `@opentelemetry/semantic-conventions` version `1.22+`, which implements Semantic Convention [Version 1.7.0](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.7.0/semantic_conventions/README.md)

Attributes collected:

| Attribute                                     | Short Description                                                                              | Service  |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------- | -------- |
| `http.status_code`                            | (aws-sdk) HTTP response status code.                                                           |          |
| `rpc.method`                                  | The name of the (logical) method being called.                                                 |          |
| `rpc.service`                                 | The full (logical) name of the service being called.                                           |          |
| `rpc.system`                                  | A string identifying the remoting system.                                                      |          |
| `cloud.region`                                | The AWS Region where the requested service is being accessed.                                  |          |
| `aws.dynamodb.attribute_definitions`          | The JSON-serialized value of each item in the `AttributeDefinitions` request field.            | dynamodb |
| `aws.dynamodb.consistent_read`                | The value of the `ConsistentRead` request parameter.                                           | dynamodb |
| `aws.dynamodb.consumed_capacity`              | The JSON-serialized value of each item in the `ConsumedCapacity` response field.               | dynamodb |
| `aws.dynamodb.count`                          | The value of the `Count` response parameter.                                                   | dynamodb |
| `aws.dynamodb.exclusive_start_table`          | The value of the `ExclusiveStartTableName` request parameter.                                  | dynamodb |
| `aws.dynamodb.global_secondary_index_updates` | The JSON-serialized value of each item in the the `GlobalSecondaryIndexUpdates` request field. | dynamodb |
| `aws.dynamodb.global_secondary_indexes`       | The JSON-serialized value of each item of the `GlobalSecondaryIndexes` request field.          | dynamodb |
| `aws.dynamodb.index_name`                     | The value of the `IndexName` request parameter.                                                | dynamodb |
| `aws.dynamodb.item_collection_metrics`        | The JSON-serialized value of the `ItemCollectionMetrics` response field.                       | dynamodb |
| `aws.dynamodb.limit`                          | The value of the `Limit` request parameter.                                                    | dynamodb |
| `aws.dynamodb.local_secondary_indexes`        | The JSON-serialized value of each item of the `LocalSecondaryIndexes` request field.           | dynamodb |
| `aws.dynamodb.projection`                     | The value of the `ProjectionExpression` request parameter.                                     | dynamodb |
| `aws.dynamodb.provisioned_read_capacity`      | The value of the `ProvisionedThroughput.ReadCapacityUnits` request parameter.                  | dynamodb |
| `aws.dynamodb.provisioned_write_capacity`     | The value of the `ProvisionedThroughput.WriteCapacityUnits` request parameter.                 | dynamodb |
| `aws.dynamodb.scan_forward`                   | The value of the `ScanIndexForward` request parameter.                                         | dynamodb |
| `aws.dynamodb.scanned_count`                  | The value of the `ScannedCount` response parameter.                                            | dynamodb |
| `aws.dynamodb.segment`                        | The value of the `Segment` request parameter.                                                  | dynamodb |
| `aws.dynamodb.select`                         | The value of the `Select` request parameter.                                                   | dynamodb |
| `aws.dynamodb.table_count`                    | The number of items in the `TableNames` response parameter.                                    | dynamodb |
| `aws.dynamodb.table_names`                    | The keys in the `RequestItems` object field.                                                   | dynamodb |
| `aws.dynamodb.total_segments`                 | The value of the `TotalSegments` request parameter.                                            | dynamodb |
| `db.name`                                     | The name of the database being accessed.                                                       | dynamodb |
| `db.operation`                                | The name of the operation being executed.                                                      | dynamodb |
| `db.statement`                                | The database statement being executed.                                                         | dynamodb |
| `db.system`                                   | An identifier for the database management system (DBMS) product being used.                    | dynamodb |
| `faas.execution`                              | The execution ID of the current function execution.                                            | lambda   |
| `faas.invoked_name`                           | The name of the invoked function.                                                              | lambda   |
| `faas.invoked_provider`                       | The cloud provider of the invoked function.                                                    | lambda   |
| `faas.invoked_region`                         | The cloud region of the invoked function.                                                      | lambda   |
| `messaging.destination`                       | The message destination name.                                                                  | sns, sqs |
| `messaging.destination_kind`                  | The kind of message destination.                                                               | sns, sqs |
| `messaging.system`                            | A string identifying the messaging system.                                                     | sns, sqs |
| `messaging.operation`                         | A string identifying the kind of message consumption.                                          | sqs      |
| `messaging.message_id`                        | A value used by the messaging system as an identifier for the message.                         | sqs      |
| `messaging.url`                               | The connection string.                                                                         | sqs      |

## Useful links

- For more information on OpenTelemetry, visit: <https://opentelemetry.io/>
- For more about OpenTelemetry JavaScript: <https://github.com/open-telemetry/opentelemetry-js>
- For help or feedback on this project, join us in [GitHub Discussions][discussions-url]

## License

Apache 2.0 - See [LICENSE][license-url] for more information.

[discussions-url]: https://github.com/open-telemetry/opentelemetry-js/discussions
[license-url]: https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/LICENSE
[license-image]: https://img.shields.io/badge/license-Apache_2.0-green.svg?style=flat
[npm-url]: https://www.npmjs.com/package/@opentelemetry/instrumentation-aws-sdk
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Finstrumentation-aws-sdk.svg
