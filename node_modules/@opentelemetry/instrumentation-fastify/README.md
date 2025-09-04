# OpenTelemetry Fastify Instrumentation for Node.js

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-image]

> [!IMPORTANT]
> This component is **deprecated** in favor of the official instrumentation package [`@fastify/otel`](https://www.npmjs.com/package/@fastify/otel), maintained by the Fastify authors.
> Please see [here](https://github.com/fastify/otel?tab=readme-ov-file#usage) for instructions on how to use `@fastify/otel`.
>
> We will stop publishing new versions of `@opentelemetry/instrumentation-fastify` on June 30, 2025.

This module provides automatic instrumentation for the [`fastify`](https://www.fastify.dev/) module, which may be loaded using the [`@opentelemetry/sdk-trace-node`](https://github.com/open-telemetry/opentelemetry-js/tree/main/packages/opentelemetry-sdk-trace-node) package.

Compatible with OpenTelemetry JS API and SDK `1.0+`.

## Installation

This instrumentation relies on HTTP calls to also be instrumented. Make sure you install and enable both, otherwise you will have spans that are not connected with each other.

```bash
npm install --save @opentelemetry/instrumentation-http @opentelemetry/instrumentation-fastify
```

### Supported Versions

- [`fastify`](https://www.npmjs.com/package/fastify) versions `>=3.0.0 <5`

## Usage

OpenTelemetry fastify Instrumentation allows the user to automatically collect trace data and export them to their backend of choice, to give observability to distributed systems.

To load the instrumentation, specify it in the Node Tracer's configuration:

```js
const { NodeTracerProvider } = require('@opentelemetry/node');
const { registerInstrumentations } = require('@opentelemetry/instrumentation');
const { HttpInstrumentation } = require('@opentelemetry/instrumentation-http');
const { FastifyInstrumentation } = require('@opentelemetry/instrumentation-fastify');

const provider = new NodeTracerProvider();
provider.register();

registerInstrumentations({
  instrumentations: [
    // Fastify instrumentation expects HTTP layer to be instrumented
    new HttpInstrumentation(),
    new FastifyInstrumentation(),
  ],
});
```

See [examples/fastify](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/examples/fastify) for a short example.

## Fastify Instrumentation Options

| Options        | Type                         | Example                          | Description                                                                    |
| -------------- | ---------------------------- | -------------------------------- | ------------------------------------------------------------------------------ |
| `requestHook`  | `FastifyCustomAttributeFunction` | `(span, requestInfo) => {}`       | Function for adding custom attributes to Fastify requests. Receives parameters: `Span, FastifyRequestInfo`. |

### Using `requestHook`

Instrumentation configuration accepts a custom "hook" function which will be called for every instrumented Fastify request. Custom attributes can be set on the span or run any custom logic per request.

```javascript
import { FastifyInstrumentation } from "@opentelemetry/instrumentation-fastify"

const fastifyInstrumentation = new FastifyInstrumentation({
  requestHook: function (span: Span, info: FastifyRequestInfo) {
    span.setAttribute(
      'http.method',
      info.request.method,
    )
  }
});
```

## Semantic Conventions

This package uses `@opentelemetry/semantic-conventions` version `1.22+`, which implements Semantic Convention [Version 1.7.0](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.7.0/semantic_conventions/README.md)

Attributes collected:

| Attribute    | Short Description                  |
| ------------ | ---------------------------------- |
| `http.route` | The matched route (path template). |

## Useful links

- For more information on OpenTelemetry, visit: <https://opentelemetry.io/>
- For more about OpenTelemetry JavaScript: <https://github.com/open-telemetry/opentelemetry-js>
- For help or feedback on this project, join us in [GitHub Discussions][discussions-url]

## License

Apache 2.0 - See [LICENSE][license-url] for more information.

[discussions-url]: https://github.com/open-telemetry/opentelemetry-js/discussions
[license-url]: https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/LICENSE
[license-image]: https://img.shields.io/badge/license-Apache_2.0-green.svg?style=flat
[npm-url]: https://www.npmjs.com/package/@opentelemetry/instrumentation-fastify
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Finstrumentation-fastify.svg
