# OpenTelemetry AWS Lambda Instrumentation for Node.js

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-image]

[component owners](https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/.github/component_owners.yml): @jj22ee

This module provides automatic instrumentation for the [`AWS Lambda`](https://docs.aws.amazon.com/lambda/latest/dg/nodejs-handler.html) module, which may be loaded using the [`@opentelemetry/sdk-trace-node`](https://github.com/open-telemetry/opentelemetry-js/tree/main/packages/opentelemetry-sdk-trace-node) package and is included in the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle.

If total installation size is not constrained, it is recommended to use the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle with [@opentelemetry/sdk-node](`https://www.npmjs.com/package/@opentelemetry/sdk-node`) for the most seamless instrumentation experience.

Compatible with OpenTelemetry JS API and SDK `1.0+`.

This module is currently under active development and not ready for general use.

## Installation

```bash
npm install --save @opentelemetry/instrumentation-aws-lambda
```

## Supported Versions

- This package will instrument the lambda execution regardless of versions.

## Usage

Create a file to initialize the instrumentation, such as `lambda-wrapper.js`.

```js
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const { AwsLambdaInstrumentation } = require('@opentelemetry/instrumentation-aws-lambda');
const { registerInstrumentations } = require('@opentelemetry/instrumentation');

const provider = new NodeTracerProvider();
provider.register();

registerInstrumentations({
  instrumentations: [
    new AwsLambdaInstrumentation({
        // see under for available configuration
    })
  ],
});
```

In your Lambda function configuration, add or update the `NODE_OPTIONS` environment variable to require the wrapper, e.g.,

`NODE_OPTIONS=--require lambda-wrapper`

## AWS Lambda Instrumentation Options

| Options | Type  | Description |
| --- | --- | --- |
| `requestHook` | `RequestHook` (function) | Hook for adding custom attributes before lambda starts handling the request. Receives params: `span, { event, context }` |
| `responseHook` | `ResponseHook` (function) | Hook for adding custom attributes before lambda returns the response. Receives params: `span, { err?, res? }` |
| `eventContextExtractor` | `EventContextExtractor` (function) | Function for providing custom context extractor in order to support different event types that are handled by AWS Lambda (e.g., SQS, CloudWatch, Kinesis, API Gateway). |
| `lambdaHandler` | `string` | By default, this instrumentation automatically determines the Lambda handler function to instrument. This option is used to override that behavior by explicitly specifying the Lambda handler to instrument. See [Specifying the Lambda Handler](#specifying-the-lambda-handler) for additional information. |

### Hooks Usage Example

```js
const { AwsLambdaInstrumentation } = require('@opentelemetry/instrumentation-aws-lambda');

new AwsLambdaInstrumentation({
    requestHook: (span, { event, context }) => {
        span.setAttribute('faas.name', context.functionName);
    },
    responseHook: (span, { err, res }) => {
        if (err instanceof Error) span.setAttribute('faas.error', err.message);
        if (res) span.setAttribute('faas.res', res);
    }
})
```

### Specifying the Lambda Handler

The instrumentation will attempt to automatically determine the Lambda handler function to instrument. To do this, it relies on the `_HANDLER` environment variable which is [set by the Lambda runtime](https://docs.aws.amazon.com/lambda/latest/dg/configuration-envvars.html#configuration-envvars-runtime). For most use cases, this will accurately represent the handler that should be targeted by this instrumentation.

There exist use cases where the `_HANDLER` environment variable does not accurately represent the module that should be targeted by this instrumentation. For these use cases, the `lambdaHandler` option can be used to explicitly specify the Lambda handler that should be instrumented.

To better explain when `lambdaHandler` should be specified, consider how some telemetry tools, such as [Datadog](https://www.datadoghq.com/), are instrumented into the Lambda runtime. Datadog does this by overriding the handler function with a wrapper function that is loaded via a [Lambda Layer](https://docs.aws.amazon.com/lambda/latest/dg/chapter-layers.html). In these examples, the Lambda's handler will point to the Datadog wrapper and not to the actual handler that should be instrumented. In cases like this, `lambdaHandler` should be used to explicitly specify the handler that should be instrumented.

The `lambdaHandler` should be specified as a string in the format `<file>.<handler>`, where `<file>` is the name of the file that contains the handler and `<handler>` is the name of the handler function. For example, if the handler is defined in the file `index.js` and the handler function is named `handler`, the `lambdaHandler` should be specified as `index.handler`.

One way to determine if the `lambdaHandler` option should be used is to check the handler defined on your Lambda. This can be done by determining the value of the `_HANDLER` environment variable or by viewing the **Runtime Settings** of your Lambda in AWS Console. If the handler is what you expect, then the instrumentation should work without the `lambdaHandler` option. If the handler points to something else, then the `lambdaHandler` option should be used to explicitly specify the handler that should be instrumented.

### Context Propagation

AWS Active Tracing can provide a parent context for the span generated by this instrumentation. Note that the span generated by Active Tracing is always reported only to AWS X-Ray. Therefore, if the OpenTelemetry SDK is configured to export traces to a backend other than AWS X-Ray, this will result in a broken trace.

If you use version `<=0.46.0` of this package, then the Active Tracing context is used as the parent context by default if present. In this case, in order to prevent broken traces, set the `disableAwsContextPropagation` option to `false`.
Additional propagators can be added in the TracerProvider configuration.

If you use version `>0.46.0`, the Active Tracing context is no longer used by default. In order to enable it, include the [AWSXRayLambdaPropagator](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/propagator-aws-xray-lambda) propagator in the list of propagators provided to the TracerProvider via its configuration, or by including `xray-lambda` in the OTEL_PROPAGATORS environment variable (see the example below on using the env variable).

Note that there are two AWS-related propagators: [AWSXRayPropagator](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/propagator-aws-xray) and [AWSXRayLambdaPropagator](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/propagator-aws-xray-lambda). Here is a guideline for when to use one or the other:

- If you export traces to AWS X-Ray, then use the `AWSXRayLambdaPropagator` or the `xray-lambda` value in the OTEL_PROPAGATORS environment variable. This will handle the active tracing lambda context as well as X-Ray HTTP headers.
- If you export traces to a backend other than AWS X-Ray, then use the `AWSXrayPropagator` or `xray` in the environment variable. This propagator only handles the X-Ray HTTP headers.

Examples:

1. Active Tracing is enabled and the OpenTelemetry SDK is configured to export traces to AWS X-Ray. In this case, configure the SDK to use the `AWSXRayLambdaPropagator`.

```js
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const { AWSXRayLambdaPropagator } = require('@opentelemetry/propagator-aws-xray-lambda');

const provider = new NodeTracerProvider();
provider.register({
  propagator: new AWSXRayLambdaPropagator()
});
```

Alternatively, use the `getPropagators()` function from the [auto-configuration-propagators](https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/packages/auto-configuration-propagators/README.md) package, and set the OTEL_PROPAGATORS environment variable to `xray-lambda`.

```js
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const { getPropagator } = require('@opentelemetry/auto-configuration-propagators');

const provider = new NodeTracerProvider();
provider.register({
  propagator: getPropagator()
});
```

1. The OpenTelemetry SDK is configured to export traces to a backend other than AWX X-Ray, but the lambda function is invoked by other AWS services which send the context using the X-Ray HTTP headers. In this case, include the `AWSXRayPropagator`, which extracts context from the HTTP header but not the Lambda Active Tracing context.

```js
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const { AWSXRayLambdaPropagator } = require('@opentelemetry/propagator-aws-xray-lambda');

const provider = new NodeTracerProvider();
provider.register({
  propagator: new AWSXRayPropagator()
});
```

Alternatively, use the `auto-configuration-package` as in example #1 and set the OTEL_PROPAGATORS environment variable to `xray`.

For additional information, see the [documentation for lambda semantic conventions](https://github.com/open-telemetry/semantic-conventions/blob/main/docs/faas/aws-lambda.md#aws-x-ray-active-tracing-considerations).

## Semantic Conventions

This package uses `@opentelemetry/semantic-conventions` version `1.22+`, which implements Semantic Convention [Version 1.7.0](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.7.0/semantic_conventions/README.md)

Attributes collected:

| Attribute          | Short Description                                                         |
| ------------------ | ------------------------------------------------------------------------- |
| `cloud.account.id` | The cloud account ID the resource is assigned to.                         |
| `faas.execution`   | The execution ID of the current function execution.                       |
| `faas.id`          | The unique ID of the single function that this runtime instance executes. |

## Useful links

- For more information on OpenTelemetry, visit: <https://opentelemetry.io/>
- For more about OpenTelemetry JavaScript: <https://github.com/open-telemetry/opentelemetry-js>
- For help or feedback on this project, join us in [GitHub Discussions][discussions-url]

## License

Apache 2.0 - See [LICENSE][license-url] for more information.

[discussions-url]: https://github.com/open-telemetry/opentelemetry-js/discussions
[license-url]: https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/LICENSE
[license-image]: https://img.shields.io/badge/license-Apache_2.0-green.svg?style=flat
[npm-url]: https://www.npmjs.com/package/@opentelemetry/instrumentation-aws-lambda
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Finstrumentation-aws-lambda.svg
