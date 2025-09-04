# OpenTelemetry MySQL Instrumentation for Node.js

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-image]

This module provides automatic instrumentation for the [`mysql`](https://www.npmjs.com/package/mysql) module, which may be loaded using the [`@opentelemetry/sdk-trace-node`](https://github.com/open-telemetry/opentelemetry-js/tree/main/packages/opentelemetry-sdk-trace-node) package and is included in the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle.

If total installation size is not constrained, it is recommended to use the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle with [@opentelemetry/sdk-node](`https://www.npmjs.com/package/@opentelemetry/sdk-node`) for the most seamless instrumentation experience.

Compatible with OpenTelemetry JS API and SDK `1.0+`.

## Installation

```bash
npm install --save @opentelemetry/instrumentation-mysql
```

## Supported Versions

- [`mysql`](https://www.npmjs.com/package/mysql) versions `>=2.0.0 <3`

## Usage

OpenTelemetry MySQL Instrumentation allows the user to automatically collect trace data and export them to the backend of choice, to give observability to distributed systems when working with [mysql](https://www.npmjs.com/package/mysql).

To load a specific plugin (**MySQL** in this case), specify it in the registerInstrumentations's configuration

```js
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const { MySQLInstrumentation } = require('@opentelemetry/instrumentation-mysql');
const { registerInstrumentations } = require('@opentelemetry/instrumentation');

const provider = new NodeTracerProvider();
provider.register();

registerInstrumentations({
  instrumentations: [
    new MySQLInstrumentation(),
  ],
})
```

See [examples/mysql](https://github.com/open-telemetry/opentelemetry-js-contrib/tree/main//examples/mysql) for a short example.

### MySQL instrumentation Options

| Options | Type | Default | Description |
| ------- | ---- | --------| ----------- |
| [`enhancedDatabaseReporting`](./src/types.ts#L24) | `boolean` | `false` | If true, an attribute containing the query's parameters will be attached the spans generated to represent the query |


## Semantic Conventions

This package uses `@opentelemetry/semantic-conventions` version `1.22+`, which implements Semantic Convention [Version 1.7.0](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.7.0/semantic_conventions/README.md)

Attributes collected:

| Attribute               | Short Description                                                              |
| ----------------------- | ------------------------------------------------------------------------------ |
| `db.connection_string`  | The connection string used to connect to the database.                         |
| `db.name`               | This attribute is used to report the name of the database being accessed.      |
| `db.operation`          | The name of the operation being executed.                                      |
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
[npm-url]: https://www.npmjs.com/package/@opentelemetry/instrumentation-mysql
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Finstrumentation-mysql.svg
