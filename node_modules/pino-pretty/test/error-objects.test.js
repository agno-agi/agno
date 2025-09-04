'use strict'

process.env.TZ = 'UTC'

const { Writable } = require('node:stream')
const { describe, test, afterEach, beforeEach } = require('node:test')
const pino = require('pino')
const semver = require('semver')
const serializers = pino.stdSerializers
const pinoPretty = require('../')
const _prettyFactory = pinoPretty.prettyFactory

function prettyFactory (opts) {
  if (!opts) {
    opts = { colorize: false }
  } else if (!Object.prototype.hasOwnProperty.call(opts, 'colorize')) {
    opts.colorize = false
  }
  return _prettyFactory(opts)
}

// All dates are computed from 'Fri, 30 Mar 2018 17:35:28 GMT'
const epoch = 1522431328992
const formattedEpoch = '17:35:28.992'
const pid = process.pid

describe('error like objects tests', () => {
  beforeEach(() => {
    Date.originalNow = Date.now
    Date.now = () => epoch
  })
  afterEach(() => {
    Date.now = Date.originalNow
    delete Date.originalNow
  })

  test('pino transform prettifies Error', (t) => {
    t.plan(2)
    const pretty = prettyFactory()
    const err = Error('hello world')
    const expected = err.stack.split('\n')
    expected.unshift(err.message)

    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        const lines = formatted.split('\n')
        t.assert.strictEqual(lines.length, expected.length + 6)
        t.assert.strictEqual(lines[0], `[${formattedEpoch}] INFO (${pid}): hello world`)
        cb()
      }
    }))

    log.info(err)
  })

  test('errorProps recognizes user specified properties', (t) => {
    t.plan(3)
    const pretty = prettyFactory({ errorProps: 'statusCode,originalStack' })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.match(formatted, /\s{4}error stack/)
        t.assert.match(formatted, /"statusCode": 500/)
        t.assert.match(formatted, /"originalStack": "original stack"/)
        cb()
      }
    }))

    const error = Error('error message')
    error.stack = 'error stack'
    error.statusCode = 500
    error.originalStack = 'original stack'

    log.error(error)
  })

  test('prettifies ignores undefined errorLikeObject', (t) => {
    const pretty = prettyFactory()
    pretty({ err: undefined })
    pretty({ error: undefined })
  })

  test('prettifies Error in property within errorLikeObjectKeys', (t) => {
    t.plan(8)
    const pretty = prettyFactory({
      errorLikeObjectKeys: ['err']
    })

    const err = Error('hello world')
    const expected = err.stack.split('\n')
    expected.unshift(err.message)

    const log = pino({ serializers: { err: serializers.err } }, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        const lines = formatted.split('\n')
        t.assert.strictEqual(lines.length, expected.length + 6)
        t.assert.strictEqual(lines[0], `[${formattedEpoch}] INFO (${pid}): hello world`)
        t.assert.match(lines[1], /\s{4}err: {/)
        t.assert.match(lines[2], /\s{6}"type": "Error",/)
        t.assert.match(lines[3], /\s{6}"message": "hello world",/)
        t.assert.match(lines[4], /\s{6}"stack":/)
        t.assert.match(lines[5], /\s{6}Error: hello world/)
        // Node 12 labels the test `<anonymous>`
        t.assert.match(lines[6], /\s{10}at TestContext.<anonymous>/)
        cb()
      }
    }))

    log.info({ err })
  })

  test('prettifies Error in property with singleLine=true', (t) => {
    // singleLine=true doesn't apply to errors
    t.plan(8)
    const pretty = prettyFactory({
      singleLine: true,
      errorLikeObjectKeys: ['err']
    })

    const err = Error('hello world')
    const expected = [
      '{"extra":{"a":1,"b":2}}',
      err.message,
      ...err.stack.split('\n')
    ]

    const log = pino({ serializers: { err: serializers.err } }, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        const lines = formatted.split('\n')
        t.assert.strictEqual(lines.length, expected.length + 5)
        t.assert.strictEqual(lines[0], `[${formattedEpoch}] INFO (${pid}): hello world {"extra":{"a":1,"b":2}}`)
        t.assert.match(lines[1], /\s{4}err: {/)
        t.assert.match(lines[2], /\s{6}"type": "Error",/)
        t.assert.match(lines[3], /\s{6}"message": "hello world",/)
        t.assert.match(lines[4], /\s{6}"stack":/)
        t.assert.match(lines[5], /\s{6}Error: hello world/)
        // Node 12 labels the test `<anonymous>`
        t.assert.match(lines[6], /\s{10}at TestContext.<anonymous>/)
        cb()
      }
    }))

    log.info({ err, extra: { a: 1, b: 2 } })
  })

  test('prettifies Error in property within errorLikeObjectKeys with custom function', (t) => {
    t.plan(4)
    const pretty = prettyFactory({
      errorLikeObjectKeys: ['err'],
      customPrettifiers: {
        err: val => `error is ${val.message}`
      }
    })

    const err = Error('hello world')
    err.stack = 'Error: hello world\n    at anonymous (C:\\project\\node_modules\\example\\index.js)'
    const expected = err.stack.split('\n')
    expected.unshift(err.message)

    const log = pino({ serializers: { err: serializers.err } }, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        const lines = formatted.split('\n')
        t.assert.strictEqual(lines.length, 3)
        t.assert.strictEqual(lines[0], `[${formattedEpoch}] INFO (${pid}): hello world`)
        t.assert.strictEqual(lines[1], '    err: error is hello world')
        t.assert.strictEqual(lines[2], '')

        cb()
      }
    }))

    log.info({ err })
  })

  test('prettifies Error in property within errorLikeObjectKeys when stack has escaped characters', (t) => {
    t.plan(8)
    const pretty = prettyFactory({
      errorLikeObjectKeys: ['err']
    })

    const err = Error('hello world')
    err.stack = 'Error: hello world\n    at anonymous (C:\\project\\node_modules\\example\\index.js)'
    const expected = err.stack.split('\n')
    expected.unshift(err.message)

    const log = pino({ serializers: { err: serializers.err } }, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        const lines = formatted.split('\n')
        t.assert.strictEqual(lines.length, expected.length + 6)
        t.assert.strictEqual(lines[0], `[${formattedEpoch}] INFO (${pid}): hello world`)
        t.assert.match(lines[1], /\s{4}err: {$/)
        t.assert.match(lines[2], /\s{6}"type": "Error",$/)
        t.assert.match(lines[3], /\s{6}"message": "hello world",$/)
        t.assert.match(lines[4], /\s{6}"stack":$/)
        t.assert.match(lines[5], /\s{10}Error: hello world$/)
        t.assert.match(lines[6], /\s{10}at anonymous \(C:\\project\\node_modules\\example\\index.js\)$/)
        cb()
      }
    }))

    log.info({ err })
  })

  test('prettifies Error in property within errorLikeObjectKeys when stack is not the last property', (t) => {
    t.plan(9)
    const pretty = prettyFactory({
      errorLikeObjectKeys: ['err']
    })

    const err = Error('hello world')
    err.anotherField = 'dummy value'
    const expected = err.stack.split('\n')
    expected.unshift(err.message)

    const log = pino({ serializers: { err: serializers.err } }, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        const lines = formatted.split('\n')
        t.assert.strictEqual(lines.length, expected.length + 7)
        t.assert.strictEqual(lines[0], `[${formattedEpoch}] INFO (${pid}): hello world`)
        t.assert.match(lines[1], /\s{4}err: {/)
        t.assert.match(lines[2], /\s{6}"type": "Error",/)
        t.assert.match(lines[3], /\s{6}"message": "hello world",/)
        t.assert.match(lines[4], /\s{6}"stack":/)
        t.assert.match(lines[5], /\s{6}Error: hello world/)
        // Node 12 labels the test `<anonymous>`
        t.assert.match(lines[6], /\s{10}at TestContext.<anonymous>/)
        t.assert.match(lines[lines.length - 3], /\s{6}"anotherField": "dummy value"/)
        cb()
      }
    }))

    log.info({ err })
  })

  test('errorProps flag with "*" (print all nested props)', function (t) {
    const pretty = prettyFactory({ errorProps: '*' })
    const expectedLines = [
      '    err: {',
      '      "type": "Error",',
      '      "message": "error message",',
      '      "stack":',
      '          error stack',
      '      "statusCode": 500,',
      '      "originalStack": "original stack",',
      '      "dataBaseSpecificError": {',
      '        "erroMessage": "some database error message",',
      '        "evenMoreSpecificStuff": {',
      '          "someErrorRelatedObject": "error"',
      '        }',
      '      }',
      '    }'
    ]
    t.plan(expectedLines.length)
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        const lines = formatted.split('\n')
        lines.shift(); lines.pop()
        for (let i = 0; i < lines.length; i += 1) {
          t.assert.strictEqual(lines[i], expectedLines[i])
        }
        cb()
      }
    }))

    const error = Error('error message')
    error.stack = 'error stack'
    error.statusCode = 500
    error.originalStack = 'original stack'
    error.dataBaseSpecificError = {
      erroMessage: 'some database error message',
      evenMoreSpecificStuff: {
        someErrorRelatedObject: 'error'
      }
    }

    log.error(error)
  })

  test('prettifies legacy error object at top level when singleLine=true', function (t) {
    t.plan(4)
    const pretty = prettyFactory({ singleLine: true })
    const err = Error('hello world')
    const expected = err.stack.split('\n')
    expected.unshift(err.message)

    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        const lines = formatted.split('\n')
        t.assert.strictEqual(lines.length, expected.length + 1)
        t.assert.strictEqual(lines[0], `[${formattedEpoch}] INFO (${pid}): ${expected[0]}`)
        t.assert.strictEqual(lines[1], `    ${expected[1]}`)
        t.assert.strictEqual(lines[2], `    ${expected[2]}`)
        cb()
      }
    }))

    log.info({ type: 'Error', stack: err.stack, msg: err.message })
  })

  test('errorProps: legacy error object at top level', function (t) {
    const pretty = prettyFactory({ errorProps: '*' })
    const expectedLines = [
      'INFO:',
      '    error stack',
      '    message: hello message',
      '    statusCode: 500',
      '    originalStack: original stack',
      '    dataBaseSpecificError: {',
      '        errorMessage: "some database error message"',
      '        evenMoreSpecificStuff: {',
      '          "someErrorRelatedObject": "error"',
      '        }',
      '    }',
      ''
    ]

    t.plan(expectedLines.length)

    const error = {}
    error.level = 30
    error.message = 'hello message'
    error.type = 'Error'
    error.stack = 'error stack'
    error.statusCode = 500
    error.originalStack = 'original stack'
    error.dataBaseSpecificError = {
      errorMessage: 'some database error message',
      evenMoreSpecificStuff: {
        someErrorRelatedObject: 'error'
      }
    }

    const formatted = pretty(JSON.stringify(error))
    const lines = formatted.split('\n')
    for (let i = 0; i < lines.length; i += 1) {
      t.assert.strictEqual(lines[i], expectedLines[i])
    }
  })

  test('errorProps flag with a single property', function (t) {
    const pretty = prettyFactory({ errorProps: 'originalStack' })
    const expectedLines = [
      'INFO:',
      '    error stack',
      '    originalStack: original stack',
      ''
    ]
    t.plan(expectedLines.length)

    const error = {}
    error.level = 30
    error.message = 'hello message'
    error.type = 'Error'
    error.stack = 'error stack'
    error.statusCode = 500
    error.originalStack = 'original stack'
    error.dataBaseSpecificError = {
      erroMessage: 'some database error message',
      evenMoreSpecificStuff: {
        someErrorRelatedObject: 'error'
      }
    }

    const formatted = pretty(JSON.stringify(error))
    const lines = formatted.split('\n')
    for (let i = 0; i < lines.length; i += 1) {
      t.assert.strictEqual(lines[i], expectedLines[i])
    }
  })

  test('errorProps flag with a single property non existent', function (t) {
    const pretty = prettyFactory({ errorProps: 'originalStackABC' })
    const expectedLines = [
      'INFO:',
      '    error stack',
      ''
    ]
    t.plan(expectedLines.length)

    const error = {}
    error.level = 30
    error.message = 'hello message'
    error.type = 'Error'
    error.stack = 'error stack'
    error.statusCode = 500
    error.originalStack = 'original stack'
    error.dataBaseSpecificError = {
      erroMessage: 'some database error message',
      evenMoreSpecificStuff: {
        someErrorRelatedObject: 'error'
      }
    }

    const formatted = pretty(JSON.stringify(error))
    const lines = formatted.split('\n')
    for (let i = 0; i < lines.length; i += 1) {
      t.assert.strictEqual(lines[i], expectedLines[i])
    }
  })

  test('handles errors with a null stack', (t) => {
    t.plan(2)
    const pretty = prettyFactory()
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.match(formatted, /\s{4}message: "foo"/)
        t.assert.match(formatted, /\s{4}stack: null/)
        cb()
      }
    }))

    const error = { message: 'foo', stack: null }
    log.error(error)
  })

  test('handles errors with a null stack for Error object', (t) => {
    const pretty = prettyFactory()
    const expectedLines = [
      '      "type": "Error",',
      '      "message": "error message",',
      '      "stack":',
      '          ',
      '      "some": "property"'
    ]
    t.plan(expectedLines.length)
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        const lines = formatted.split('\n')
        lines.shift(); lines.shift(); lines.pop(); lines.pop()
        for (let i = 0; i < lines.length; i += 1) {
          t.assert.ok(lines[i].includes(expectedLines[i]))
        }
        cb()
      }
    }))

    const error = Error('error message')
    error.stack = null
    error.some = 'property'

    log.error(error)
  })
})

if (semver.gte(pino.version, '8.21.0')) {
  describe('using pino config', () => {
    beforeEach(() => {
      Date.originalNow = Date.now
      Date.now = () => epoch
    })
    afterEach(() => {
      Date.now = Date.originalNow
      delete Date.originalNow
    })

    test('prettifies Error in custom errorKey', (t) => {
      t.plan(8)
      const destination = new Writable({
        write (chunk, enc, cb) {
          const formatted = chunk.toString()
          const lines = formatted.split('\n')
          t.assert.strictEqual(lines.length, expected.length + 7)
          t.assert.strictEqual(lines[0], `[${formattedEpoch}] INFO (${pid}): hello world`)
          t.assert.match(lines[1], /\s{4}customErrorKey: {/)
          t.assert.match(lines[2], /\s{6}"type": "Error",/)
          t.assert.match(lines[3], /\s{6}"message": "hello world",/)
          t.assert.match(lines[4], /\s{6}"stack":/)
          t.assert.match(lines[5], /\s{6}Error: hello world/)
          // Node 12 labels the test `<anonymous>`
          t.assert.match(lines[6], /\s{10}(at Test.await t.test|at Test.<anonymous>)/)
          cb()
        }
      })
      const pretty = pinoPretty({
        destination,
        colorize: false
      })
      const log = pino({ errorKey: 'customErrorKey' }, pretty)
      const err = Error('hello world')
      const expected = err.stack.split('\n')
      log.info({ customErrorKey: err })
    })
  })
}
