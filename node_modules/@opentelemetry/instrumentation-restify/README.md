# OpenTelemetry Restify Instrumentation for Node.js

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-image]

This module provides automatic instrumentation for the [`restify`](https://github.com/restify/node-restify) module, which may be loaded using the [`@opentelemetry/sdk-trace-node`](https://github.com/open-telemetry/opentelemetry-js/tree/main/packages/opentelemetry-sdk-trace-node) package and is included in the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle. It allows the user to automatically collect trace data and export them to their backend of choice.

If total installation size is not constrained, it is recommended to use the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle with [@opentelemetry/sdk-node](`https://www.npmjs.com/package/@opentelemetry/sdk-node`) for the most seamless instrumentation experience.

Compatible with OpenTelemetry JS API and SDK `1.0+`.

## Installation

```bash
npm install --save @opentelemetry/instrumentation-restify
```

### Supported Versions

- [`restify`](https://www.npmjs.com/package/restify) versions `>=4.1.0 <12`

## Usage

```js
const { RestifyInstrumentation } = require('@opentelemetry/instrumentation-restify');
const { ConsoleSpanExporter, SimpleSpanProcessor } = require('@opentelemetry/sdk-trace-base');
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const { registerInstrumentations } = require('@opentelemetry/instrumentation');

const provider = new NodeTracerProvider({
  spanProcessors: [
    new SimpleSpanProcessor(new ConsoleSpanExporter()),
  ]
});

provider.register();

registerInstrumentations({
  instrumentations: [
    new RestifyInstrumentation()
  ],
});
```

See [examples/restify](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/examples/restify) for a short example.

## Restify Instrumentation Options

| Options | Type | Example | Description |
| `requestHook` | `RestifyCustomAttributeFunction` | `(span, requestInfo) => {}` | Function for adding custom attributes to restify requests. Receives params: `Span, RestifyRequestInfo`. |

### Using `requestHook`

Instrumentation configuration accepts a custom "hook" function which will be called for every instrumented restify request. Custom attributes can be set on the span or run any custom logic per request.

```javascript
import { RestifyInstrumentation } from "@opentelemetry/instrumentation-restify"
const restifyInstrumentation = new RestifyInstrumentation({
  requestHook: function (span: Span, info: RestifyRequestInfo) {
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
[npm-url]: https://www.npmjs.com/package/@opentelemetry/instrumentation-restify
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Finstrumentation-restify.svg
