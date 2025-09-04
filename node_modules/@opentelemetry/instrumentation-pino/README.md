# OpenTelemetry instrumentation for pino

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-image]

This module provides automatic instrumentation of the [`pino`](https://www.npmjs.com/package/pino) module to inject trace-context into Pino log records (log correlation) and to send Pino logging to the OpenTelemetry Logging SDK (log sending). It may be loaded using the [`@opentelemetry/sdk-trace-node`](https://github.com/open-telemetry/opentelemetry-js/tree/main/packages/opentelemetry-sdk-trace-node) package and is included in the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle.

If total installation size is not constrained, it is recommended to use the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle with [@opentelemetry/sdk-node](`https://www.npmjs.com/package/@opentelemetry/sdk-node`) for the most seamless instrumentation experience.

Compatible with OpenTelemetry JS API and SDK `1.0+`.

## Installation

```bash
npm install --save @opentelemetry/instrumentation-pino
```

## Supported Versions

- [`pino`](https://www.npmjs.com/package/pino) versions `>=5.14.0 <10`
  - The "log sending" feature is only supported in pino v7 and later.

## Usage

```js
const { NodeSDK, tracing, logs, api } = require('@opentelemetry/sdk-node');
const { PinoInstrumentation } = require('@opentelemetry/instrumentation-pino');
const sdk = new NodeSDK({
  spanProcessor: new tracing.SimpleSpanProcessor(new tracing.ConsoleSpanExporter()),
  logRecordProcessor: new logs.SimpleLogRecordProcessor(new logs.ConsoleLogRecordExporter()),
  instrumentations: [
    new PinoInstrumentation({
      // See below for Pino instrumentation options.
    }),
  ]
})
sdk.start();

const pino = require('pino');
const logger = pino();

logger.info('hi');
// 1. Log records will be sent to the SDK-registered log record processor, if any.
//    This is called "log sending".

const tracer = api.trace.getTracer('example');
tracer.startActiveSpan('manual-span', span => {
  logger.info('in a span');
  // 2. Fields identifying the current span will be added to log records:
  //    {"level":30,...,"msg":"in a span","trace_id":"d61b4e4af1032e0aae279d12f3ab0159","span_id":"d140da862204f2a2","trace_flags":"01"}
  //    This feature is called "log correlation".
});
```

### Log sending

Creation of a Pino Logger will automatically add a [Pino destination](https://getpino.io/#/docs/api?id=pinooptions-destination-gt-logger) that sends log records to the OpenTelemetry Logs SDK. The OpenTelemetry SDK can be configured to handle those records -- for example, sending them on to an OpenTelemetry collector for log archiving and processing. The example above shows a minimal configuration that emits OpenTelemetry log records to the console for debugging.

If the OpenTelemetry SDK is not configured with a Logger provider, then this added destination will be a no-op.

Log sending can be disabled with the `disableLogSending: true` option.

### Log correlation

Pino logger calls in the context of a tracing span will have fields identifying the span added to the log record. This allows [correlating](https://opentelemetry.io/docs/specs/otel/logs/#log-correlation) log records with tracing data. The added fields are ([spec](https://opentelemetry.io/docs/specs/otel/compatibility/logging_trace_context/)):

- `trace_id`
- `span_id`
- `trace_flags`

These field names can optionally be configured via the `logKeys` option. For example:

```js
    new PinoInstrumentation({
      logKeys: {
        traceId: 'myTraceId',
        spanId: 'mySpanId',
        traceFlags: 'myTraceFlags',
      },
    }),
```

After adding these fields, the optional `logHook` is called to allow injecting additional fields. For example:

```js
  logHook: (span, record) => {
    record['resource.service.name'] = provider.resource.attributes['service.name'];
  }
```

When no span context is active or the span context is invalid, injection is skipped.
Log injection can be disabled with the `disableLogCorrelation: true` option.

### Pino instrumentation options

| Option                  | Type              | Description |
| ----------------------- | ----------------- | ----------- |
| `disableLogSending`     | `boolean`         | Whether to disable [log sending](#log-sending). Default `false`. |
| `disableLogCorrelation` | `boolean`         | Whether to disable [log correlation](#log-correlation). Default `false`. |
| `logKeys`               | record            | A record with keys `traceId`, `spanId`, and `traceFlags` string fields giving the field names to use for log-correlation span data. |
| `logHook`               | `LogHookFunction` | An option hook to inject additional context to a log record after trace-context has been added. This requires `disableLogCorrelation` to be false. |

## Semantic Conventions

This package does not currently generate any attributes from semantic conventions.

## Alternative log sending with `pino-opentelemetry-transport`

A possible alternative to the "log sending" support provided by this instrumentation is the [`pino-opentelemetry-transport` package](https://github.com/pinojs/pino-opentelemetry-transport).

Every Pino logger has an output ["destination"](https://getpino.io/#/docs/api?id=destination), for example, a file or stdout.  Since v7, Pino includes support for ["transports"](https://getpino.io/#/docs/transports), a type of destination that uses a [worker thread](https://nodejs.org/api/worker_threads.html) to run the transport code. When calling `logger.info("hi")`, Pino serializes the log record to a JSON string, [sends that string to the worker](https://nodejs.org/api/worker_threads.html#workerpostmessagevalue-transferlist) for it to be handled.

The `pino-opentelemetry-transport` package uses this mechanism. It starts an OpenTelemetry SDK `LoggerProvider` in the worker thread, parses each log record string, translates it into the OpenTelemetry Logs data model and sends it. Note that this `LoggerProvider` is independent of any OpenTelemetry SDK components in the main thread.

The log sending support in this instrumentation works on the main thread and uses the OpenTelemetry SDK configured in the main thread. Otherwise the two mechanisms are very similar. Note that because they are maintained separately, there might be small differences in how Pino log records are translated into the OpenTelemetry Logs data model.

## Useful links

- For more information on OpenTelemetry, visit: <https://opentelemetry.io/>
- For more about OpenTelemetry JavaScript: <https://github.com/open-telemetry/opentelemetry-js>
- For help or feedback on this project, join us in [GitHub Discussions][discussions-url]

## License

Apache 2.0 - See [LICENSE][license-url] for more information.

[discussions-url]: https://github.com/open-telemetry/opentelemetry-js/discussions
[license-url]: https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/LICENSE
[license-image]: https://img.shields.io/badge/license-Apache_2.0-green.svg?style=flat
[npm-url]: https://www.npmjs.com/package/@opentelemetry/instrumentation-pino
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Finstrumentation-pino.svg
