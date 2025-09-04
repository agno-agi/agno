'use strict'

process.env.TZ = 'UTC'

const { Writable } = require('node:stream')
const os = require('node:os')
const { describe, test, beforeEach, afterEach } = require('node:test')
const match = require('@jsumners/assert-match')
const pino = require('pino')
const dateformat = require('dateformat')
const rimraf = require('rimraf')
const { join } = require('node:path')
const fs = require('node:fs')
const semver = require('semver')
const pinoPretty = require('..')
const SonicBoom = require('sonic-boom')
const _prettyFactory = pinoPretty.prettyFactory

// Disable pino warnings
process.removeAllListeners('warning')

function prettyFactory (opts) {
  if (!opts) {
    opts = { colorize: false }
  } else if (!Object.prototype.hasOwnProperty.call(opts, 'colorize')) {
    opts.colorize = false
  }
  return _prettyFactory(opts)
}

const Empty = function () {}
Empty.prototype = Object.create(null)

// All dates are computed from 'Fri, 30 Mar 2018 17:35:28 GMT'
const epoch = 1522431328992
const formattedEpoch = '17:35:28.992'
const pid = process.pid
const hostname = os.hostname()

describe('basic prettifier tests', () => {
  beforeEach(() => {
    Date.originalNow = Date.now
    Date.now = () => epoch
  })
  afterEach(() => {
    Date.now = Date.originalNow
    delete Date.originalNow
  })

  test('preserves output if not valid JSON', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const formatted = pretty('this is not json\nit\'s just regular output\n')
    t.assert.strictEqual(formatted, 'this is not json\nit\'s just regular output\n\n')
  })

  test('formats a line without any extra options', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] INFO (${pid}): foo\n`
        )
        cb()
      }
    }))
    log.info('foo')
  })

  test('will add color codes', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ colorize: true })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] \u001B[32mINFO\u001B[39m (${pid}): \u001B[36mfoo\u001B[39m\n`
        )
        cb()
      }
    }))
    log.info('foo')
  })

  test('will omit color codes from objects when colorizeObjects = false', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ colorize: true, singleLine: true, colorizeObjects: false })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] \u001B[32mINFO\u001B[39m (${pid}): \u001B[36mfoo\u001B[39m {"foo":"bar"}\n`
        )
        cb()
      }
    }))
    log.info({ foo: 'bar' }, 'foo')
  })

  test('can swap date and level position', (t) => {
    t.plan(1)
    const destination = new Writable({
      write (formatted, enc, cb) {
        t.assert.strictEqual(
          formatted.toString(),
          `INFO [${formattedEpoch}] (${pid}): foo\n`
        )
        cb()
      }
    })
    const pretty = pinoPretty({
      destination,
      levelFirst: true,
      colorize: false
    })
    const log = pino({}, pretty)
    log.info('foo')
  })

  test('can print message key value when its a string', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] INFO (${pid}): baz\n`
        )
        cb()
      }
    }))
    log.info('baz')
  })

  test('can print message key value when its a number', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] INFO (${pid}): 42\n`
        )
        cb()
      }
    }))
    log.info(42)
  })

  test('can print message key value when its a Number(0)', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] INFO (${pid}): 0\n`
        )
        cb()
      }
    }))
    log.info(0)
  })

  test('can print message key value when its a boolean', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] INFO (${pid}): true\n`
        )
        cb()
      }
    }))
    log.info(true)
  })

  test('can use different message keys', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ messageKey: 'bar' })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] INFO (${pid}): baz\n`
        )
        cb()
      }
    }))
    log.info({ bar: 'baz' })
  })

  test('can use different level keys', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ levelKey: 'bar' })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] WARN (${pid}): foo\n`
        )
        cb()
      }
    }))
    log.info({ msg: 'foo', bar: 'warn' })
  })

  test('can use nested level keys', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ levelKey: 'log\\.level' })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] WARN (${pid}): foo\n`
        )
        cb()
      }
    }))
    log.info({ msg: 'foo', 'log.level': 'warn' })
  })

  test('can use a customPrettifier on default level output', (t) => {
    t.plan(1)
    const veryCustomLevels = {
      30: 'ok',
      40: 'not great'
    }
    const customPrettifiers = {
      level: (level) => `LEVEL: ${veryCustomLevels[level]}`
    }
    const pretty = prettyFactory({ customPrettifiers })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] LEVEL: ok (${pid}): foo\n`
        )
        cb()
      }
    }))
    log.info({ msg: 'foo' })
  })

  test('can use a customPrettifier on different-level-key output', (t) => {
    t.plan(1)
    const customPrettifiers = {
      level: (level) => `LEVEL: ${level.toUpperCase()}`
    }
    const pretty = prettyFactory({ levelKey: 'bar', customPrettifiers })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] LEVEL: WARN (${pid}): foo\n`
        )
        cb()
      }
    }))
    log.info({ msg: 'foo', bar: 'warn' })
  })

  test('can use a customPrettifier to get final level label (no color)', (t) => {
    t.plan(1)
    const customPrettifiers = {
      level: (level, key, logThis, { label }) => {
        return `LEVEL: ${label}`
      }
    }
    const pretty = prettyFactory({ customPrettifiers, colorize: false, useOnlyCustomProps: false })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] LEVEL: INFO (${pid}): foo\n`
        )
        cb()
      }
    }))
    log.info({ msg: 'foo' })
  })

  test('can use a customPrettifier to get final level label (colorized)', (t) => {
    t.plan(1)
    const customPrettifiers = {
      level: (level, key, logThis, { label, labelColorized }) => {
        return `LEVEL: ${labelColorized}`
      }
    }
    const pretty = prettyFactory({ customPrettifiers, colorize: true, useOnlyCustomProps: false })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] LEVEL: [32mINFO[39m (${pid}): [36mfoo[39m\n`
        )
        cb()
      }
    }))
    log.info({ msg: 'foo' })
  })

  test('can use a customPrettifier on name output', (t) => {
    t.plan(1)
    const customPrettifiers = {
      name: (hostname) => `NAME: ${hostname}`
    }
    const pretty = prettyFactory({ customPrettifiers })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] INFO (NAME: logger/${pid}): foo\n`
        )
        cb()
      }
    }))
    const child = log.child({ name: 'logger' })
    child.info({ msg: 'foo' })
  })

  test('can use a customPrettifier on hostname and pid output', (t) => {
    t.plan(1)
    const customPrettifiers = {
      hostname: (hostname) => `HOSTNAME: ${hostname}`,
      pid: (pid) => `PID: ${pid}`
    }
    const pretty = prettyFactory({ customPrettifiers, ignore: '' })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] INFO (PID: ${pid} on HOSTNAME: ${hostname}): foo\n`
        )
        cb()
      }
    }))
    log.info({ msg: 'foo' })
  })

  test('can use a customPrettifier on default time output', (t) => {
    t.plan(1)
    const customPrettifiers = {
      time: (timestamp) => `TIME: ${timestamp}`
    }
    const pretty = prettyFactory({ customPrettifiers })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `TIME: ${formattedEpoch} INFO (${pid}): foo\n`
        )
        cb()
      }
    }))
    log.info('foo')
  })

  test('can use a customPrettifier on the caller', (t) => {
    t.plan(1)
    const customPrettifiers = {
      caller: (caller) => `CALLER: ${caller}`
    }
    const pretty = prettyFactory({ customPrettifiers })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] INFO (${pid}) <CALLER: test.js:10>: foo\n`
        )
        cb()
      }
    }))
    log.info({ msg: 'foo', caller: 'test.js:10' })
  })

  test('can use a customPrettifier on translateTime-time output', (t) => {
    t.plan(1)
    const customPrettifiers = {
      time: (timestamp) => `TIME: ${timestamp}`
    }
    const pretty = prettyFactory({ customPrettifiers, translateTime: true })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `TIME: ${formattedEpoch} INFO (${pid}): foo\n`
        )
        cb()
      }
    }))
    log.info('foo')
  })

  test('will format time to UTC', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ translateTime: true })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] INFO (${pid}): foo\n`
        )
        cb()
      }
    }))
    log.info('foo')
  })

  test('will format time to UTC in custom format', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ translateTime: 'HH:MM:ss o' })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        const utcHour = dateformat(epoch, 'UTC:' + 'HH')
        const offset = dateformat(epoch, 'UTC:' + 'o')
        t.assert.strictEqual(
          formatted,
          `[${utcHour}:35:28 ${offset}] INFO (${pid}): foo\n`
        )
        cb()
      }
    }))
    log.info('foo')
  })

  test('will format time to local systemzone in ISO 8601 format', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ translateTime: 'sys:standard' })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        const localHour = dateformat(epoch, 'HH')
        const localMinute = dateformat(epoch, 'MM')
        const localDate = dateformat(epoch, 'yyyy-mm-dd')
        const offset = dateformat(epoch, 'o')
        t.assert.strictEqual(
          formatted,
          `[${localDate} ${localHour}:${localMinute}:28.992 ${offset}] INFO (${pid}): foo\n`
        )
        cb()
      }
    }))
    log.info('foo')
  })

  test('will format time to local systemzone in custom format', (t) => {
    t.plan(1)
    const pretty = prettyFactory({
      translateTime: 'SYS:yyyy/mm/dd HH:MM:ss o'
    })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        const localHour = dateformat(epoch, 'HH')
        const localMinute = dateformat(epoch, 'MM')
        const localDate = dateformat(epoch, 'yyyy/mm/dd')
        const offset = dateformat(epoch, 'o')
        t.assert.strictEqual(
          formatted,
          `[${localDate} ${localHour}:${localMinute}:28 ${offset}] INFO (${pid}): foo\n`
        )
        cb()
      }
    }))
    log.info('foo')
  })

  // TODO: 2019-03-30 -- We don't really want the indentation in this case? Or at least some better formatting.
  test('handles missing time', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const formatted = pretty('{"hello":"world"}')
    t.assert.strictEqual(formatted, '    hello: "world"\n')
  })

  test('handles missing pid, hostname and name', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const log = pino({ base: null }, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.match(formatted, /\[.*\] INFO: hello world/)
        cb()
      }
    }))
    log.info('hello world')
  })

  test('handles missing pid', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const name = 'test'
    const msg = 'hello world'
    const regex = new RegExp('\\[.*\\] INFO \\(' + name + '\\): ' + msg)

    const opts = {
      base: {
        name,
        hostname
      }
    }
    const log = pino(opts, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.match(formatted, regex)
        cb()
      }
    }))

    log.info(msg)
  })

  test('handles missing hostname', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const name = 'test'
    const msg = 'hello world'
    const regex = new RegExp('\\[.*\\] INFO \\(' + name + '/' + pid + '\\): ' + msg)

    const opts = {
      base: {
        name,
        pid: process.pid
      }
    }
    const log = pino(opts, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.match(formatted, regex)
        cb()
      }
    }))

    log.info(msg)
  })

  test('handles missing name', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const msg = 'hello world'
    const regex = new RegExp('\\[.*\\] INFO \\(' + process.pid + '\\): ' + msg)

    const opts = {
      base: {
        hostname,
        pid: process.pid
      }
    }
    const log = pino(opts, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.match(formatted, regex)
        cb()
      }
    }))

    log.info(msg)
  })

  test('works without time', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const log = pino({ timestamp: null }, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(formatted, `INFO (${pid}): hello world\n`)
        cb()
      }
    }))
    log.info('hello world')
  })

  test('prettifies properties', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        match(formatted, '    a: "b"', t)
        cb()
      }
    }))
    log.info({ a: 'b' }, 'hello world')
  })

  test('prettifies nested properties', (t) => {
    t.plan(6)
    const expectedLines = [
      '    a: {',
      '      "b": {',
      '        "c": "d"',
      '      }',
      '    }'
    ]
    const pretty = prettyFactory()
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        const lines = formatted.split('\n')
        t.assert.strictEqual(lines.length, expectedLines.length + 2)
        lines.shift(); lines.pop()
        for (let i = 0; i < lines.length; i += 1) {
          t.assert.strictEqual(lines[i], expectedLines[i])
        }
        cb()
      }
    }))
    log.info({ a: { b: { c: 'd' } } }, 'hello world')
  })

  test('treats the name with care', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const log = pino({ name: 'matteo' }, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(formatted, `[${formattedEpoch}] INFO (matteo/${pid}): hello world\n`)
        cb()
      }
    }))
    log.info('hello world')
  })

  test('handles spec allowed primitives', (t) => {
    const pretty = prettyFactory()
    let formatted = pretty(null)
    t.assert.strictEqual(formatted, 'null\n')

    formatted = pretty(true)
    t.assert.strictEqual(formatted, 'true\n')

    formatted = pretty(false)
    t.assert.strictEqual(formatted, 'false\n')
  })

  test('handles numbers', (t) => {
    const pretty = prettyFactory()
    let formatted = pretty(2)
    t.assert.strictEqual(formatted, '2\n')

    formatted = pretty(-2)
    t.assert.strictEqual(formatted, '-2\n')

    formatted = pretty(0.2)
    t.assert.strictEqual(formatted, '0.2\n')

    formatted = pretty(Infinity)
    t.assert.strictEqual(formatted, 'Infinity\n')

    formatted = pretty(NaN)
    t.assert.strictEqual(formatted, 'NaN\n')
  })

  test('handles `undefined` input', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const formatted = pretty(undefined)
    t.assert.strictEqual(formatted, 'undefined\n')
  })

  test('handles customLogLevel', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const log = pino({ customLevels: { testCustom: 35 } }, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.match(formatted, /USERLVL/)
        cb()
      }
    }))
    log.testCustom('test message')
  })

  test('filter some lines based on minimumLevel', (t) => {
    t.plan(3)
    const pretty = prettyFactory({ minimumLevel: 'info' })
    const expected = [
      undefined,
      undefined,
      `[${formattedEpoch}] INFO (${pid}): baz\n`
    ]
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          expected.shift()
        )
        cb()
      }
    }))
    log.info({ msg: 'foo', level: 10 })
    log.info({ msg: 'bar', level: 20 })
    // only this line will be formatted
    log.info({ msg: 'baz', level: 30 })
  })

  test('filter lines based on minimumLevel using custom levels and level key', (t) => {
    t.plan(3)
    const pretty = prettyFactory({ minimumLevel: 20, levelKey: 'bar' })
    const expected = [
      undefined,
      `[${formattedEpoch}] DEBUG (${pid}): bar\n`,
      `[${formattedEpoch}] INFO (${pid}): baz\n`
    ]
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          expected.shift()
        )
        cb()
      }
    }))
    log.info({ msg: 'foo', bar: 10 })
    log.info({ msg: 'bar', bar: 20 })
    log.info({ msg: 'baz', bar: 30 })
  })

  test('formats a line with an undefined field', (t) => {
    t.plan(1)
    const pretty = prettyFactory()
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const obj = JSON.parse(chunk.toString())
        // weird hack, but we should not crash
        obj.a = undefined
        const formatted = pretty(obj)
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] INFO (${pid}): foo\n`
        )
        cb()
      }
    }))
    log.info('foo')
  })

  test('prettifies msg object', (t) => {
    t.plan(6)
    const expectedLines = [
      '    msg: {',
      '      "b": {',
      '        "c": "d"',
      '      }',
      '    }'
    ]
    const pretty = prettyFactory()
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        const lines = formatted.split('\n')
        t.assert.strictEqual(lines.length, expectedLines.length + 2)
        lines.shift(); lines.pop()
        for (let i = 0; i < lines.length; i += 1) {
          t.assert.strictEqual(lines[i], expectedLines[i])
        }
        cb()
      }
    }))
    log.info({ msg: { b: { c: 'd' } } })
  })

  test('prettifies msg object with circular references', (t) => {
    t.plan(7)
    const expectedLines = [
      '    msg: {',
      '      "a": "[Circular]",',
      '      "b": {',
      '        "c": "d"',
      '      }',
      '    }'
    ]
    const pretty = prettyFactory()
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        const lines = formatted.split('\n')
        t.assert.strictEqual(lines.length, expectedLines.length + 2)
        lines.shift(); lines.pop()
        for (let i = 0; i < lines.length; i += 1) {
          t.assert.strictEqual(lines[i], expectedLines[i])
        }
        cb()
      }
    }))

    const msg = { b: { c: 'd' } }
    msg.a = msg
    log.info({ msg })
  })

  test('prettifies custom key', (t) => {
    t.plan(1)
    const pretty = prettyFactory({
      customPrettifiers: {
        foo: val => `${val}_baz\nmultiline`,
        cow: val => val.toUpperCase()
      }
    })
    const arst = pretty('{"msg":"hello world", "foo": "bar", "cow": "moo", "level":30}')
    t.assert.strictEqual(arst, 'INFO: hello world\n    foo: bar_baz\n    multiline\n    cow: MOO\n')
  })

  test('does not add trailing space if prettified value begins with eol', (t) => {
    t.plan(1)
    const pretty = prettyFactory({
      customPrettifiers: {
        calls: val => '\n' + val.map(it => '  ' + it).join('\n')
      }
    })
    const arst = pretty('{"msg":"doing work","calls":["step 1","step 2","step 3"],"level":30}')
    t.assert.strictEqual(arst, 'INFO: doing work\n    calls:\n      step 1\n      step 2\n      step 3\n')
  })

  test('does not prettify custom key that does not exists', (t) => {
    t.plan(1)
    const pretty = prettyFactory({
      customPrettifiers: {
        foo: val => `${val}_baz`,
        cow: val => val.toUpperCase()
      }
    })
    const arst = pretty('{"msg":"hello world", "foo": "bar", "level":30}')
    t.assert.strictEqual(arst, 'INFO: hello world\n    foo: bar_baz\n')
  })

  test('prettifies object with some undefined values', (t) => {
    t.plan(1)
    const destination = new Writable({
      write (chunk, _, cb) {
        t.assert.strictEqual(
          chunk + '',
          `[${formattedEpoch}] INFO (${pid}):\n    a: {\n      "b": "c"\n    }\n    n: null\n`
        )
        cb()
      }
    })
    const pretty = pinoPretty({
      destination,
      colorize: false
    })
    const log = pino({}, pretty)
    log.info({
      a: { b: 'c' },
      s: Symbol.for('s'),
      f: f => f,
      c: class C {},
      n: null,
      err: { toJSON () {} }
    })
  })

  test('ignores multiple keys', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ ignore: 'pid,hostname' })
    const arst = pretty(`{"msg":"hello world", "pid":"${pid}", "hostname":"${hostname}", "time":${epoch}, "level":30}`)
    t.assert.strictEqual(arst, `[${formattedEpoch}] INFO: hello world\n`)
  })

  test('ignores a single key', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ ignore: 'pid' })
    const arst = pretty(`{"msg":"hello world", "pid":"${pid}", "hostname":"${hostname}", "time":${epoch}, "level":30}`)
    t.assert.strictEqual(arst, `[${formattedEpoch}] INFO (on ${hostname}): hello world\n`)
  })

  test('ignores time', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ ignore: 'time' })
    const arst = pretty(`{"msg":"hello world", "pid":"${pid}", "hostname":"${hostname}", "time":${epoch}, "level":30}`)
    t.assert.strictEqual(arst, `INFO (${pid} on ${hostname}): hello world\n`)
  })

  test('ignores time and level', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ ignore: 'time,level' })
    const arst = pretty(`{"msg":"hello world", "pid":"${pid}", "hostname":"${hostname}", "time":${epoch}, "level":30}`)
    t.assert.strictEqual(arst, `(${pid} on ${hostname}): hello world\n`)
  })

  test('ignores all keys but message', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ ignore: 'time,level,name,pid,hostname' })
    const arst = pretty(`{"msg":"hello world", "pid":"${pid}", "hostname":"${hostname}", "time":${epoch}, "level":30}`)
    t.assert.strictEqual(arst, 'hello world\n')
  })

  test('include nothing', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ include: '' })
    const arst = pretty(`{"msg":"hello world", "pid":"${pid}", "hostname":"${hostname}", "time":${epoch}, "level":30}`)
    t.assert.strictEqual(arst, 'hello world\n')
  })

  test('include multiple keys', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ include: 'time,level' })
    const arst = pretty(`{"msg":"hello world", "pid":"${pid}", "hostname":"${hostname}", "time":${epoch}, "level":30}`)
    t.assert.strictEqual(arst, `[${formattedEpoch}] INFO: hello world\n`)
  })

  test('include a single key', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ include: 'level' })
    const arst = pretty(`{"msg":"hello world", "pid":"${pid}", "hostname":"${hostname}", "time":${epoch}, "level":30}`)
    t.assert.strictEqual(arst, 'INFO: hello world\n')
  })

  test('log error-like object', (t) => {
    t.plan(7)
    const expectedLines = [
      '    type: "Error"',
      '    message: "m"',
      '    stack: [',
      '      "line1",',
      '      "line2"',
      '    ]'
    ]
    const pretty = prettyFactory()
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        const lines = formatted.split('\n')
        t.assert.strictEqual(lines.length, expectedLines.length + 2)
        lines.shift(); lines.pop()
        for (let i = 0; i < lines.length; i += 1) {
          t.assert.strictEqual(lines[i], expectedLines[i])
        }
        cb()
      }
    }))
    log.error({ type: 'Error', message: 'm', stack: ['line1', 'line2'] })
  })

  test('include should override ignore', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ ignore: 'time,level', include: 'time,level' })
    const arst = pretty(`{"msg":"hello world", "pid":"${pid}", "hostname":"${hostname}", "time":${epoch}, "level":30}`)
    t.assert.strictEqual(arst, `[${formattedEpoch}] INFO: hello world\n`)
  })

  test('include a single key with null object', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ include: 'level' })
    const obj = new Empty()
    obj.nested = 'property'
    const arst = pretty({
      msg: 'hello world',
      pid: `${pid}`,
      hostname,
      time: epoch,
      obj,
      level: 30
    })
    t.assert.strictEqual(arst, 'INFO: hello world\n')
  })

  test('prettifies trace caller', (t) => {
    t.plan(1)
    const traceCaller = (instance) => {
      const { symbols: { asJsonSym } } = pino
      const get = (target, name) => name === asJsonSym ? asJson : target[name]

      function asJson (...args) {
        args[0] = args[0] || {}
        args[0].caller = '/tmp/script.js'
        return instance[asJsonSym].apply(this, args)
      }

      return new Proxy(instance, { get })
    }

    const pretty = prettyFactory()
    const log = traceCaller(pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] INFO (${pid}) </tmp/script.js>: foo\n`
        )
        cb()
      }
    })))
    log.info('foo')
  })

  test('handles specified timestampKey', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ timestampKey: '@timestamp' })
    const arst = pretty(`{"msg":"hello world", "@timestamp":${epoch}, "level":30}`)
    t.assert.strictEqual(arst, `[${formattedEpoch}] INFO: hello world\n`)
  })

  test('keeps "v" key in log', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ ignore: 'time' })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(formatted, `INFO (${pid} on ${hostname}):\n    v: 1\n`)
        cb()
      }
    }))
    log.info({ v: 1 })
  })

  test('Hide object `{ key: "value" }` from output when flag `hideObject` is set', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ hideObject: true })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(formatted, `[${formattedEpoch}] INFO (${pid}): hello world\n`)
        cb()
      }
    }))
    log.info({ key: 'value' }, 'hello world')
  })

  test('Prints extra objects on one line with singleLine=true', (t) => {
    t.plan(1)
    const pretty = prettyFactory({
      singleLine: true,
      colorize: false,
      customPrettifiers: {
        upper: val => val.toUpperCase(),
        undef: () => undefined
      }
    })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(formatted, `[${formattedEpoch}] INFO (${pid}): message {"extra":{"foo":"bar","number":42},"upper":"FOOBAR"}\n`)

        cb()
      }
    }))
    log.info({ msg: 'message', extra: { foo: 'bar', number: 42 }, upper: 'foobar', undef: 'this will not show up' })
  })

  test('Does not print empty object with singleLine=true', (t) => {
    t.plan(1)
    const pretty = prettyFactory({ singleLine: true, colorize: false })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(formatted, `[${formattedEpoch}] INFO (${pid}): message\n`)
        cb()
      }
    }))
    log.info({ msg: 'message' })
  })

  test('default options', (t) => {
    t.plan(1)
    t.assert.doesNotThrow(pinoPretty)
  })

  test('does not call fs.close on stdout stream', (t) => {
    t.plan(2)
    const destination = pino.destination({ minLength: 4096, sync: true })
    const prettyDestination = pinoPretty({ destination, colorize: false })
    const log = pino(prettyDestination)
    log.info('this message has been buffered')
    const chunks = []
    const { close, writeSync } = fs
    let closeCalled = false
    fs.close = new Proxy(close, {
      apply: (target, self, args) => {
        closeCalled = true
      }
    })
    fs.writeSync = new Proxy(writeSync, {
      apply: (target, self, args) => {
        chunks.push(args[1])
        return args[1].length
      }
    })
    destination.end()
    Object.assign(fs, { close, writeSync })
    t.assert.match(chunks.join(''), /INFO .+: this message has been buffered/)
    t.assert.strictEqual(closeCalled, false)
  })

  test('wait for close event from destination', (t, end) => {
    t.plan(2)
    const destination = pino.destination({ minLength: 4096, sync: true })
    const prettyDestination = pinoPretty({ destination, colorize: false })
    const log = pino(prettyDestination)
    log.info('this message has been buffered')
    const chunks = []
    const { close, writeSync } = fs
    fs.close = new Proxy(close, {
      apply: (target, self, args) => {
      }
    })
    fs.writeSync = new Proxy(writeSync, {
      apply: (target, self, args) => {
        chunks.push(args[1])
        return args[1].length
      }
    })
    t.after(() => {
      Object.assign(fs, { close, writeSync })
    })
    let destinationClosed = false
    destination.on('close', () => {
      destinationClosed = true
    })
    prettyDestination.on('close', () => {
      t.assert.match(chunks.join(''), /INFO .+: this message has been buffered/)
      t.assert.strictEqual(destinationClosed, true)
      end()
    })
    prettyDestination.end()
  })

  test('stream usage', async (t) => {
    t.plan(1)
    const tmpDir = join(__dirname, '.tmp_' + Date.now())
    t.after(() => rimraf.sync(tmpDir))

    const destination = join(tmpDir, 'output')

    const pretty = pinoPretty({
      singleLine: true,
      colorize: false,
      mkdir: true,
      append: false,
      destination: new SonicBoom({ dest: destination, async: false, mkdir: true, append: true }),
      customPrettifiers: {
        upper: val => val.toUpperCase(),
        undef: () => undefined
      }
    })
    const log = pino(pretty)
    log.info({ msg: 'message', extra: { foo: 'bar', number: 42 }, upper: 'foobar', undef: 'this will not show up' })

    await watchFileCreated(destination)

    const formatted = fs.readFileSync(destination, 'utf8')

    t.assert.strictEqual(formatted, `[${formattedEpoch}] INFO (${pid}): message {"extra":{"foo":"bar","number":42},"upper":"FOOBAR"}\n`)
  })

  test('sync option', async (t) => {
    t.plan(1)
    const tmpDir = join(__dirname, '.tmp_' + Date.now())
    t.after(() => rimraf.sync(tmpDir))

    const destination = join(tmpDir, 'output')

    const log = pino(pino.transport({
      target: '..',
      options: {
        singleLine: true,
        colorize: false,
        mkdir: true,
        append: false,
        sync: true,
        destination
      }
    }))
    log.info({ msg: 'message', extra: { foo: 'bar', number: 43 }, upper: 'foobar' })

    await watchFileCreated(destination)

    const formatted = fs.readFileSync(destination, 'utf8')

    t.assert.strictEqual(formatted, `[${formattedEpoch}] INFO (${pid}): message {"extra":{"foo":"bar","number":43},"upper":"foobar"}\n`)
  })

  test('support custom colors object', async (t) => {
    t.plan(1)
    const pretty = prettyFactory({
      colorize: true,
      customColors: {
        trace: 'cyan',
        debug: 'blue',
        info: 'green',
        warn: 'yellow',
        error: 'red',
        fatal: 'red'
      }
    })
    const log = pino({}, new Writable({
      write (chunk, enc, cb) {
        const formatted = pretty(chunk.toString())
        t.assert.strictEqual(
          formatted,
          `[${formattedEpoch}] \u001B[32mINFO\u001B[39m (${pid}): \u001B[36mfoo\u001B[39m\n`
        )
        cb()
      }
    }))
    log.info('foo')
  })

  test('check support for colors', (t) => {
    t.plan(1)
    const isColorSupported = pinoPretty.isColorSupported
    t.assert.strictEqual(typeof isColorSupported, 'boolean')
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

    test('can use different message keys', (t) => {
      t.plan(1)
      const destination = new Writable({
        write (formatted, enc, cb) {
          t.assert.strictEqual(
            formatted.toString(),
            `[${formattedEpoch}] INFO (${pid}): baz\n`
          )
          cb()
        }
      })
      const pretty = pinoPretty({
        destination,
        colorize: false
      })
      const log = pino({ messageKey: 'bar' }, pretty)
      log.info({ bar: 'baz' })
    })

    test('handles customLogLevels', (t) => {
      t.plan(1)
      const destination = new Writable({
        write (formatted, enc, cb) {
          t.assert.strictEqual(
            formatted.toString(),
            `[${formattedEpoch}] TESTCUSTOM (${pid}): test message\n`
          )
          cb()
        }
      })
      const pretty = pinoPretty({
        destination,
        colorize: false
      })
      const log = pino({ customLevels: { testCustom: 35 } }, pretty)
      log.testCustom('test message')
    })
  })
}

function watchFileCreated (filename) {
  return new Promise((resolve, reject) => {
    const TIMEOUT = 2000
    const INTERVAL = 100
    const threshold = TIMEOUT / INTERVAL
    let counter = 0
    const interval = setInterval(() => {
      // On some CI runs file is created but not filled
      if (fs.existsSync(filename) && fs.statSync(filename).size !== 0) {
        clearInterval(interval)
        resolve()
      } else if (counter <= threshold) {
        counter++
      } else {
        clearInterval(interval)
        reject(new Error(`${filename} was not created.`))
      }
    }, INTERVAL)
  })
}
