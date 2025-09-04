# OpenTelemetry instrumentation for bunyan

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-image]

This module provides automatic instrumentation of the [`bunyan`](https://www.npmjs.com/package/bunyan) module to inject trace-context into Bunyan log records (log correlation) and to send Bunyan logging to the OpenTelemetry Logging SDK (log sending). It may be loaded using the [`@opentelemetry/sdk-trace-node`](https://github.com/open-telemetry/opentelemetry-js/tree/main/packages/opentelemetry-sdk-trace-node) package and is included in the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle.

If total installation size is not constrained, it is recommended to use the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle with [@opentelemetry/sdk-node](`https://www.npmjs.com/package/@opentelemetry/sdk-node`) for the most seamless instrumentation experience.

Compatible with OpenTelemetry JS API and SDK `1.0+`.

## Installation

```bash
npm install --save @opentelemetry/instrumentation-bunyan
```

## Supported Versions

- [`bunyan`](https://www.npmjs.com/package/bunyan) versions `>=1.0.0 <2`

## Usage

```js
const { NodeSDK, tracing, logs, api } = require('@opentelemetry/sdk-node');
const { BunyanInstrumentation } = require('@opentelemetry/instrumentation-bunyan');
const sdk = new NodeSDK({
  spanProcessor: new tracing.SimpleSpanProcessor(new tracing.ConsoleSpanExporter()),
  logRecordProcessor: new logs.SimpleLogRecordProcessor(new logs.ConsoleLogRecordExporter()),
  instrumentations: [
    new BunyanInstrumentation({
      // See below for Bunyan instrumentation options.
    }),
  ]
})
sdk.start();

const bunyan = require('bunyan');
const logger = bunyan.createLogger({name: 'example'});

logger.info('hi');
// 1. Log records will be sent to the SDK-registered log record processor, if any.
//    This is called "log sending".

const tracer = api.trace.getTracer('example');
tracer.startActiveSpan('manual-span', span => {
  logger.info('in a span');
  // 2. Fields identifying the current span will be added to log records:
  //    {"name":"example",...,"msg":"in a span","trace_id":"d61b4e4af1032e0aae279d12f3ab0159","span_id":"d140da862204f2a2","trace_flags":"01"}
  //    This is called "log correlation".
})
```

### Log sending

Creation of a Bunyan Logger will automatically add a [Bunyan stream](https://github.com/trentm/node-bunyan#streams) that sends log records to the OpenTelemetry Logs SDK. The OpenTelemetry SDK can be configured to handle those records -- for example, sending them on to an OpenTelemetry collector for log archiving and processing. The example above shows a minimal configuration that emits OpenTelemetry log records to the console for debugging.

If the OpenTelemetry SDK is not configured with a Logger provider, then this added stream will be a no-op.

Log sending can be disabled with the `disableLogSending: true` option.

### Log correlation

Bunyan logger calls in the context of a tracing span will have fields
identifying the span added to the log record. This allows
[correlating](https://opentelemetry.io/docs/specs/otel/logs/#log-correlation)
log records with tracing data. The added fields are
([spec](https://opentelemetry.io/docs/specs/otel/compatibility/logging_trace_context/)):

- `trace_id`
- `span_id`
- `trace_flags`

After adding these fields, the optional `logHook` is called to allow injecting additional fields. For example:

```js
  logHook: (span, record) => {
    record['resource.service.name'] = provider.resource.attributes['service.name'];
  }
```

When no span context is active or the span context is invalid, injection is skipped.
Log injection can be disabled with the `disableLogCorrelation: true` option.

### Bunyan instrumentation options

| Option                  | Type              | Description |
| ----------------------- | ----------------- | ----------- |
| `disableLogSending`     | `boolean`         | Whether to disable [log sending](#log-sending). Default `false`. |
| `logSeverity`           | `SeverityNumber`  | Control severity level for [log sending](#log-sending). Default `SeverityNumber.UNSPECIFIED`, it will use Bunnyan Logger's current level when unspecified. |
| `disableLogCorrelation` | `boolean`         | Whether to disable [log correlation](#log-correlation). Default `false`. |
| `logHook`               | `LogHookFunction` | An option hook to inject additional context to a log record after trace-context has been added. This requires `disableLogCorrelation` to be false. |

### Using OpenTelemetryBunyanStream without instrumentation

This package exports the Bunyan stream class that is used to send records to the
OpenTelemetry Logs SDK. It can be used directly when configuring a Bunyan logger
if one is not using the `BunyanInstrumentation` for whatever reason. For
example:

```js
const { OpenTelemetryBunyanStream } = require('@opentelemetry/instrumentation-bunyan');
const bunyan = require('bunyan');

// You must register an OpenTelemetry LoggerProvider, otherwise log records will
// be sent to a no-op implementation. "examples/telemetry.js" shows one way
// to configure one.
// ...

const logger = bunyan.createLogger({
  name: 'my-logger',
  streams: [
    {
      type: 'raw',
      stream: new OpenTelemetryBunyanStream()
    }
  ],
});
```

## Semantic Conventions

This package does not currently generate any attributes from semantic conventions.

## Useful links

- For more information on OpenTelemetry, visit: <https://opentelemetry.io/>
- For more about OpenTelemetry JavaScript: <https://github.com/open-telemetry/opentelemetry-js>
- For help or feedback on this project, join us in [GitHub Discussions][discussions-url]

## License

Apache 2.0 - See [LICENSE][license-url] for more information.

[discussions-url]: https://github.com/open-telemetry/opentelemetry-js/discussions
[license-url]: https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/LICENSE
[license-image]: https://img.shields.io/badge/license-Apache_2.0-green.svg?style=flat
[npm-url]: https://www.npmjs.com/package/@opentelemetry/instrumentation-bunyan
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Finstrumentation-bunyan.svg
