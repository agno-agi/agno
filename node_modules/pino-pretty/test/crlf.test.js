'use strict'

process.env.TZ = 'UTC'

const { describe, test } = require('node:test')
const _prettyFactory = require('../').prettyFactory

function prettyFactory (opts) {
  if (!opts) {
    opts = { colorize: false }
  } else if (!Object.prototype.hasOwnProperty.call(opts, 'colorize')) {
    opts.colorize = false
  }
  return _prettyFactory(opts)
}

const logLine = '{"level":30,"time":1522431328992,"msg":"hello world","pid":42,"hostname":"foo"}\n'

describe('crlf', () => {
  test('uses LF by default', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const formatted = pretty(logLine)
    t.assert.strictEqual(formatted.substr(-2), 'd\n')
  })

  test('can use CRLF', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ crlf: true })
    const formatted = pretty(logLine)
    t.assert.strictEqual(formatted.substr(-3), 'd\r\n')
  })
})
