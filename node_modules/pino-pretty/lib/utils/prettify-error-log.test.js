'use strict'

const { test, describe } = require('node:test')
const prettifyErrorLog = require('./prettify-error-log')
const colors = require('../colors')
const {
  ERROR_LIKE_KEYS,
  MESSAGE_KEY
} = require('../constants')

const context = {
  EOL: '\n',
  IDENT: '    ',
  customPrettifiers: {},
  errorLikeObjectKeys: ERROR_LIKE_KEYS,
  errorProps: [],
  messageKey: MESSAGE_KEY,
  objectColorizer: colors()
}

test('returns string with default settings', t => {
  const err = Error('Something went wrong')
  const str = prettifyErrorLog({ log: err, context })
  t.assert.ok(str.startsWith('    Error: Something went wrong'))
})

test('returns string with custom ident', t => {
  const err = Error('Something went wrong')
  const str = prettifyErrorLog({
    log: err,
    context: {
      ...context,
      IDENT: '  '
    }
  })
  t.assert.ok(str.startsWith('  Error: Something went wrong'))
})

test('returns string with custom eol', t => {
  const err = Error('Something went wrong')
  const str = prettifyErrorLog({
    log: err,
    context: {
      ...context,
      EOL: '\r\n'
    }
  })
  t.assert.ok(str.startsWith('    Error: Something went wrong\r\n'))
})

describe('errorProperties', () => {
  test('excludes all for wildcard', t => {
    const err = Error('boom')
    err.foo = 'foo'
    const str = prettifyErrorLog({
      log: err,
      context: {
        ...context,
        errorProps: ['*']
      }
    })
    t.assert.ok(str.startsWith('    Error: boom'))
    t.assert.strictEqual(str.includes('foo: "foo"'), false)
  })

  test('excludes only selected properties', t => {
    const err = Error('boom')
    err.foo = 'foo'
    const str = prettifyErrorLog({
      log: err,
      context: {
        ...context,
        errorProps: ['foo']
      }
    })
    t.assert.ok(str.startsWith('    Error: boom'))
    t.assert.strictEqual(str.includes('foo: foo'), true)
  })

  test('ignores specified properties if not present', t => {
    const err = Error('boom')
    err.foo = 'foo'
    const str = prettifyErrorLog({
      log: err,
      context: {
        ...context,
        errorProps: ['foo', 'bar']
      }
    })
    t.assert.ok(str.startsWith('    Error: boom'))
    t.assert.strictEqual(str.includes('foo: foo'), true)
    t.assert.strictEqual(str.includes('bar'), false)
  })

  test('processes nested objects', t => {
    const err = Error('boom')
    err.foo = { bar: 'bar', message: 'included' }
    const str = prettifyErrorLog({
      log: err,
      context: {
        ...context,
        errorProps: ['foo']
      }
    })
    t.assert.ok(str.startsWith('    Error: boom'))
    t.assert.strictEqual(str.includes('foo: {'), true)
    t.assert.strictEqual(str.includes('bar: "bar"'), true)
    t.assert.strictEqual(str.includes('message: "included"'), true)
  })
})
