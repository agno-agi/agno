# OpenTelemetry mysql Instrumentation for Node.js

[![NPM Published Version][npm-img]][npm-url]
[![Apache License][license-image]][license-image]

This module provides automatic instrumentation for the [`mysql2`](https://github.com/sidorares/node-mysql2) module, which may be loaded using the [`@opentelemetry/sdk-trace-node`](https://github.com/open-telemetry/opentelemetry-js/tree/main/packages/opentelemetry-sdk-trace-node) package and is included in the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle.

If total installation size is not constrained, it is recommended to use the [`@opentelemetry/auto-instrumentations-node`](https://www.npmjs.com/package/@opentelemetry/auto-instrumentations-node) bundle with [@opentelemetry/sdk-node](`https://www.npmjs.com/package/@opentelemetry/sdk-node`) for the most seamless instrumentation experience.

Compatible with OpenTelemetry JS API and SDK `1.0+`.

## Installation

```bash
npm install --save @opentelemetry/instrumentation-mysql2
```

## Supported Versions

- [`mysql2`](https://www.npmjs.com/package/mysql2) versions `>=1.4.2 <4`

## Usage

OpenTelemetry MySQL2 Instrumentation allows the user to automatically collect trace data and export them to the backend of choice, to give observability to distributed systems when working with [mysql2](https://github.com/sidorares/node-mysql2).

To load a specific plugin (**MySQL2** in this case), specify it in the registerInstrumentations's configuration

```js
const { NodeTracerProvider } = require('@opentelemetry/sdk-trace-node');
const { MySQL2Instrumentation } = require('@opentelemetry/instrumentation-mysql2');
const { registerInstrumentations } = require('@opentelemetry/instrumentation');

const provider = new NodeTracerProvider();
provider.register();

registerInstrumentations({
  instrumentations: [
    new MySQL2Instrumentation(),
  ],
})
```

### MySQL2 Instrumentation Options

You can set the following instrumentation options:

| Options | Type | Description |
| ------- | ---- | ----------- |
| `responseHook` | `MySQL2InstrumentationExecutionResponseHook` (function) | Function for adding custom attributes from db response |
| `addSqlCommenterCommentToQueries` | `boolean` | If true, adds [sqlcommenter](https://github.com/open-telemetry/opentelemetry-sqlcommenter) specification compliant comment to queries with tracing context (default false). _NOTE: A comment will not be added to queries that already contain `--` or `/* ... */` in them, even if these are not actually part of comments_ |
| `maskStatement` | `boolean` | If true, masks the `db.statement` attribute in spans (default false) with the `maskStatementHook` |
| `maskStatementHook` | `MySQL2InstrumentationMaskStatementHook` (function) | Function for masking the `db.statement` attribute in spans  Default: `return query.replace(/\b\d+\b/g, '?').replac(/(["'])(?:(?=(\\?))\2.)*?\1/g, '?');`|


## Semantic Conventions

This package uses `@opentelemetry/semantic-conventions` version `1.22+`, which implements Semantic Convention [Version 1.7.0](https://github.com/open-telemetry/opentelemetry-specification/blob/v1.7.0/semantic_conventions/README.md)

Attributes collected:

| Attribute               | Short Description                                                              |
| ----------------------- | ------------------------------------------------------------------------------ |
| `db.connection_string`  | The connection string used to connect to the database.                         |
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
[npm-url]: https://www.npmjs.com/package/@opentelemetry/instrumentation-mysql2
[npm-img]: https://badge.fury.io/js/%40opentelemetry%2Finstrumentation-mysql2.svg
