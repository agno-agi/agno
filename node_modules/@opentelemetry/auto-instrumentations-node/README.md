# OpenTelemetry Meta Packages for Node

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-url]

## About

This module provides a way to auto instrument any Node application to capture telemetry from a number of popular libraries and frameworks.
You can export the telemetry data in a variety of formats. Exporters, samplers, and more can be configured via [environment variables][env-var-url].
The net result is the ability to gather telemetry data from a Node application without any code changes.

This module also provides a simple way to manually initialize multiple Node instrumentations for use with the OpenTelemetry SDK.

Compatible with OpenTelemetry JS API and SDK `2.0+`.

## Installation

```bash
npm install --save @opentelemetry/api
npm install --save @opentelemetry/auto-instrumentations-node
```

## Usage: Auto Instrumentation

This module includes auto instrumentation for all supported instrumentations and [all available data exporters][exporter-url].
It provides a completely automatic, out-of-the-box experience.
Please see the [Supported Instrumentations](#supported-instrumentations) section for more information.

Enable auto instrumentation by requiring this module using the [--require flag][require-url]:

```shell
node --require '@opentelemetry/auto-instrumentations-node/register' app.js
```

If your Node application is encapsulated in a complex run script, you can also set it via an environment variable before running Node.

```shell
env NODE_OPTIONS="--require @opentelemetry/auto-instrumentations-node/register"
```

The module is highly configurable using environment variables.
Many aspects of the auto instrumentation's behavior can be configured for your needs, such as resource detectors, exporter choice, exporter configuration, trace context propagation headers, and much more.
Instrumentation configuration is not yet supported through environment variables. Users that require instrumentation configuration must initialize OpenTelemetry programmatically.

```shell
export OTEL_TRACES_EXPORTER="otlp"
export OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
export OTEL_EXPORTER_OTLP_COMPRESSION="gzip"
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="https://your-endpoint"
export OTEL_EXPORTER_OTLP_HEADERS="x-api-key=your-api-key"
export OTEL_EXPORTER_OTLP_TRACES_HEADERS="x-api-key=your-api-key"
export OTEL_RESOURCE_ATTRIBUTES="service.namespace=my-namespace"
export OTEL_NODE_RESOURCE_DETECTORS="env,host,os,serviceinstance"
export OTEL_SERVICE_NAME="client"
export NODE_OPTIONS="--require @opentelemetry/auto-instrumentations-node/register"
node app.js
```

By default, all SDK resource detectors are used, but you can use the environment variable OTEL_NODE_RESOURCE_DETECTORS to enable only certain detectors, or completely disable them:

- `env`
- `host`
- `os`
- `process`
- `serviceinstance`
- `container`
- `alibaba`
- `aws`
- `azure`
- `gcp`
- `all` - enable all resource detectors
- `none` - disable resource detection

For example, to enable only the `env`, `host` detectors:

```shell
export OTEL_NODE_RESOURCE_DETECTORS="env,host"
```

By default, all [Supported Instrumentations](#supported-instrumentations) are enabled, unless they are annotated with "default disabled".
You can use the environment variable `OTEL_NODE_ENABLED_INSTRUMENTATIONS` to enable only certain instrumentations, including "default disabled" ones
OR the environment variable `OTEL_NODE_DISABLED_INSTRUMENTATIONS` to disable only certain instrumentations,
by providing a comma-separated list of the instrumentation package names without the `@opentelemetry/instrumentation-` prefix.

For example, to enable only
[@opentelemetry/instrumentation-http](https://github.com/open-telemetry/opentelemetry-js/tree/main/packages/opentelemetry-instrumentation-http)
and [@opentelemetry/instrumentation-nestjs-core](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-nestjs-core)
instrumentations:

```shell
export OTEL_NODE_ENABLED_INSTRUMENTATIONS="http,nestjs-core"
```

To disable only [@opentelemetry/instrumentation-net](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-net):

```shell
export OTEL_NODE_DISABLED_INSTRUMENTATIONS="net"
```

If both environment variables are set, `OTEL_NODE_ENABLED_INSTRUMENTATIONS` is applied first, and then `OTEL_NODE_DISABLED_INSTRUMENTATIONS` is applied to that list.
Therefore, if the same instrumentation is included in both lists, that instrumentation will be disabled.

To enable logging for troubleshooting, set the log level by setting the `OTEL_LOG_LEVEL` environment variable to one of the following:

- `none`
- `error`
- `warn`
- `info`
- `debug`
- `verbose`
- `all`

The default level is `info`.

Notes:

- In a production environment, it is recommended to set `OTEL_LOG_LEVEL`to `info`.
- Logs are always sent to console, no matter the environment, or debug level.
- Debug logs are extremely verbose. Enable debug logging only when needed. Debug logging negatively impacts the performance of your application.

## Usage: Instrumentation Initialization

OpenTelemetry Meta Packages for Node automatically loads instrumentations for Node builtin modules and common packages.

Custom configuration for each of the instrumentations can be passed to the function, by providing an object with the name of the instrumentation as a key, and its configuration as the value.

```javascript
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const { getNodeAutoInstrumentations } = require('@opentelemetry/auto-instrumentations-node');
const { CollectorTraceExporter } = require('@opentelemetry/exporter-collector');
const { resourceFromAttributes } = require('@opentelemetry/resources');
const { SEMRESATTRS_SERVICE_NAME } = require('@opentelemetry/semantic-conventions');
const { SimpleSpanProcessor } = require('@opentelemetry/sdk-trace-base');
const { registerInstrumentations } = require('@opentelemetry/instrumentation');

const exporter = new CollectorTraceExporter();
const provider = new NodeTracerProvider({
  resource: resourceFromAttributes({
    [SEMRESATTRS_SERVICE_NAME]: 'basic-service',
  }),
  spanProcessors: [
    new SimpleSpanProcessor(exporter),
  ],
});
provider.register();

registerInstrumentations({
  instrumentations: [
    getNodeAutoInstrumentations({
      // load custom configuration for http instrumentation
      '@opentelemetry/instrumentation-http': {
        applyCustomAttributesOnSpan: (span) => {
          span.setAttribute('foo2', 'bar2');
        },
      },
    }),
  ],
});

```

## Supported instrumentations

- [@opentelemetry/instrumentation-amqplib](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-amqplib)
- [@opentelemetry/instrumentation-aws-lambda](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-aws-lambda)
- [@opentelemetry/instrumentation-aws-sdk](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-aws-sdk)
- [@opentelemetry/instrumentation-bunyan](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-bunyan)
- [@opentelemetry/instrumentation-cassandra-driver](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-cassandra-driver)
- [@opentelemetry/instrumentation-connect](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-connect)
- [@opentelemetry/instrumentation-cucumber](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-cucumber)
- [@opentelemetry/instrumentation-dataloader](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-dataloader)
- [@opentelemetry/instrumentation-dns](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-dns)
- [@opentelemetry/instrumentation-express](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-express)
- [@opentelemetry/instrumentation-fastify](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-fastify) (deprecated, default disabled)
  - This component is **deprecated** in favor of the official instrumentation package [`@fastify/otel`](https://www.npmjs.com/package/@fastify/otel), maintained by the Fastify authors.
    - Please see [here](https://github.com/fastify/otel?tab=readme-ov-file#usage) for instructions on how to use `@fastify/otel`.
  - This component will be removed on June 30, 2025
- [@opentelemetry/instrumentation-fs](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-fs) (default disabled)
- [@opentelemetry/instrumentation-generic-pool](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-generic-pool)
- [@opentelemetry/instrumentation-graphql](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-graphql)
- [@opentelemetry/instrumentation-grpc](https://github.com/open-telemetry/opentelemetry-js/tree/main/experimental/packages/opentelemetry-instrumentation-grpc)
- [@opentelemetry/instrumentation-hapi](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-hapi)
- [@opentelemetry/instrumentation-http](https://github.com/open-telemetry/opentelemetry-js/tree/main/experimental/packages/opentelemetry-instrumentation-http)
- [@opentelemetry/instrumentation-ioredis](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-ioredis)
- [@opentelemetry/instrumentation-kafkajs](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-kafkajs)
- [@opentelemetry/instrumentation-knex](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-knex)
- [@opentelemetry/instrumentation-koa](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-koa)
- [@opentelemetry/instrumentation-lru-memoizer](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-lru-memoizer)
- [@opentelemetry/instrumentation-memcached](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-memcached)
- [@opentelemetry/instrumentation-mongodb](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-mongodb)
- [@opentelemetry/instrumentation-mongoose](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-mongoose)
- [@opentelemetry/instrumentation-mysql](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-mysql)
- [@opentelemetry/instrumentation-mysql2](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-mysql2)
- [@opentelemetry/instrumentation-nestjs-core](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-nestjs-core)
- [@opentelemetry/instrumentation-net](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-net)
- [@opentelemetry/instrumentation-oracledb](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-oracledb)
- [@opentelemetry/instrumentation-pg](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-pg)
- [@opentelemetry/instrumentation-pino](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-pino)
- [@opentelemetry/instrumentation-redis](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-redis)
- [@opentelemetry/instrumentation-restify](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-restify)
- [@opentelemetry/instrumentation-runtime-node](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-runtime-node)
- [@opentelemetry/instrumentation-socket.io](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-socket.io)
- [@opentelemetry/instrumentation-undici](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-undici)
- [@opentelemetry/instrumentation-winston](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main/packages/instrumentation-winston)

## Useful links

- For more information on OpenTelemetry, visit: <https://opentelemetry.io/>
- For more about OpenTelemetry JavaScript: <https://github.com/open-telemetry/opentelemetry-js>

## License

APACHE 2.0 - See [LICENSE][license-url] for more information.

[license-url]: https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/LICENSE
[license-image]: https://img.shields.io/badge/license-Apache_2.0-green.svg?style=flat
[npm-url]: https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Fauto-instrumentations-node.svg
[env-var-url]: https://github.com/open-telemetry/opentelemetry-specification/blob/main/specification/configuration/sdk-environment-variables.md#general-sdk-configuration
[exporter-url]: https://github.com/open-telemetry/opentelemetry-specification/blob/main/specification/configuration/sdk-environment-variables.md#otlp-exporter
[require-url]: https://nodejs.org/api/cli.html#-r---require-module
