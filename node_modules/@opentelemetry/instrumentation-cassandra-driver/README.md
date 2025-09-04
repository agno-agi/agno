# OpenTelemetry instrumentation for cassandra-driver

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-image]

This module provides automatic instrumentation for the injection of trace context to [`cassandra-driver`](https://www.npmjs.com/package/cassandra-driver), which may be loaded using the [`@opentelemetry/sdk-trace-node`](https://github.com/open-telemetry/opentelemetry-js/tree/main/packages/opentelemetry-sdk-trace-node) package and is included in the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle.

If total installation size is not constrained, it is recommended to use the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle with [@opentelemetry/sdk-node](`https://www.npmjs.com/package/@opentelemetry/sdk-node`) for the most seamless instrumentation experience.

Compatible with OpenTelemetry JS API and SDK `1.0+`.

## Installation

```bash
npm install --save @opentelemetry/instrumentation-cassandra-driver
```

### Supported Versions

- [`cassandra-driver`](https://www.npmjs.com/package/cassandra-driver) versions `>=4.4.0 <5`

## Usage

```js
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const { CassandraDriverInstrumentation } = require('@opentelemetry/instrumentation-cassandra-driver');
const { registerInstrumentations } = require('@opentelemetry/instrumentation');

const provider = new NodeTracerProvider();
provider.register();

registerInstrumentations({
  instrumentations: [
    new CassandraDriverInstrumentation(),
    // other instrumentations
  ],
});

const cassandra = require('cassandra-driver');
const client = new cassandra.Client({ ... });
await client.execute('select * from foo');
```

### Instrumentation options

| Option                      | Type                                             | Default     | Description                                                                                                                                                                                                                    |
|-----------------------------|--------------------------------------------------|-------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `enhancedDatabaseReporting` | `boolean`                                        | `false`     | Whether to include database queries with spans. These can contain sensitive information when using unescaped parameters - i.e. `insert into persons (name) values ('Bob')` instead of `insert into persons (name) values (?)`. |
| `responseHook`              | `CassandraDriverResponseCustomAttributeFunction` | `undefined` | Hook for adding custom attributes before response is handled                                                                                                                                                                   |
| `maxQueryLength`            | `number`                                         | `65536`     | If `enhancedDatabaseReporting` is enabled, limits the attached query strings to this length.                                                                                                                                   |

## Semantic Conventions

This package uses `@opentelemetry/semantic-conventions` version `1.22+`, which implements Semantic Convention [Version 1.7.0](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.7.0/semantic_conventions/README.md)

Attributes collected:

| Attribute               | Short Description                                                              |
| ----------------------- | ------------------------------------------------------------------------------ |
| `db.name`               | This attribute is used to report the name of the database being accessed.      |
| `db.statement`          | The database statement being executed.                                         |
| `db.system`             | An identifier for the database management system (DBMS) product being used.    |
| `db.user`               | Username for accessing the database.                                           |
| `net.peer.name`         | Remote hostname or similar.                                                    |
| `net.peer.port`         | Remote port number.                                                            |

## Useful links

- For more information on OpenTelemetry, visit: <https://opentelemetry.io/>
- For more about OpenTelemetry JavaScript: <https://github.com/open-telemetry/opentelemetry-js>
- For help or feedback on this project, join us in [GitHub Discussions][discussions-url]

## License

Apache 2.0 - See [LICENSE][license-url] for more information.

[discussions-url]: https://github.com/open-telemetry/opentelemetry-js/discussions
[license-url]: https://github.com/open-telemetry/opentelemetry-js-contrib/blob/main/LICENSE
[license-image]: https://img.shields.io/badge/license-Apache_2.0-green.svg?style=flat
[npm-url]: https://www.npmjs.com/package/@opentelemetry/instrumentation-cassandra-driver
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Finstrumentation-cassandra-driver.svg
