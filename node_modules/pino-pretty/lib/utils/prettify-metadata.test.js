'use strict'

const { test } = require('node:test')
const prettifyMetadata = require('./prettify-metadata')
const getColorizer = require('../colors')
const context = {
  customPrettifiers: {},
  colorizer: {
    colors: {}
  }
}

test('returns `undefined` if no metadata present', t => {
  const str = prettifyMetadata({ log: {}, context })
  t.assert.strictEqual(str, undefined)
})

test('works with only `name` present', t => {
  const str = prettifyMetadata({ log: { name: 'foo' }, context })
  t.assert.strictEqual(str, '(foo)')
})

test('works with only `pid` present', t => {
  const str = prettifyMetadata({ log: { pid: '1234' }, context })
  t.assert.strictEqual(str, '(1234)')
})

test('works with only `hostname` present', t => {
  const str = prettifyMetadata({ log: { hostname: 'bar' }, context })
  t.assert.strictEqual(str, '(on bar)')
})

test('works with only `name` & `pid` present', t => {
  const str = prettifyMetadata({ log: { name: 'foo', pid: '1234' }, context })
  t.assert.strictEqual(str, '(foo/1234)')
})

test('works with only `name` & `hostname` present', t => {
  const str = prettifyMetadata({ log: { name: 'foo', hostname: 'bar' }, context })
  t.assert.strictEqual(str, '(foo on bar)')
})

test('works with only `pid` & `hostname` present', t => {
  const str = prettifyMetadata({ log: { pid: '1234', hostname: 'bar' }, context })
  t.assert.strictEqual(str, '(1234 on bar)')
})

test('works with only `name`, `pid`, & `hostname` present', t => {
  const str = prettifyMetadata({ log: { name: 'foo', pid: '1234', hostname: 'bar' }, context })
  t.assert.strictEqual(str, '(foo/1234 on bar)')
})

test('works with only `name` & `caller` present', t => {
  const str = prettifyMetadata({ log: { name: 'foo', caller: 'baz' }, context })
  t.assert.strictEqual(str, '(foo) <baz>')
})

test('works with only `pid` & `caller` present', t => {
  const str = prettifyMetadata({ log: { pid: '1234', caller: 'baz' }, context })
  t.assert.strictEqual(str, '(1234) <baz>')
})

test('works with only `hostname` & `caller` present', t => {
  const str = prettifyMetadata({ log: { hostname: 'bar', caller: 'baz' }, context })
  t.assert.strictEqual(str, '(on bar) <baz>')
})

test('works with only `name`, `pid`, & `caller` present', t => {
  const str = prettifyMetadata({ log: { name: 'foo', pid: '1234', caller: 'baz' }, context })
  t.assert.strictEqual(str, '(foo/1234) <baz>')
})

test('works with only `name`, `hostname`, & `caller` present', t => {
  const str = prettifyMetadata({ log: { name: 'foo', hostname: 'bar', caller: 'baz' }, context })
  t.assert.strictEqual(str, '(foo on bar) <baz>')
})

test('works with only `caller` present', t => {
  const str = prettifyMetadata({ log: { caller: 'baz' }, context })
  t.assert.strictEqual(str, '<baz>')
})

test('works with only `pid`, `hostname`, & `caller` present', t => {
  const str = prettifyMetadata({ log: { pid: '1234', hostname: 'bar', caller: 'baz' }, context })
  t.assert.strictEqual(str, '(1234 on bar) <baz>')
})

test('works with all four present', t => {
  const str = prettifyMetadata({ log: { name: 'foo', pid: '1234', hostname: 'bar', caller: 'baz' }, context })
  t.assert.strictEqual(str, '(foo/1234 on bar) <baz>')
})

test('uses prettifiers from passed prettifiers object', t => {
  const prettifiers = {
    name (input) {
      return input.toUpperCase()
    },
    pid (input) {
      return input + '__'
    },
    hostname (input) {
      return input.toUpperCase()
    },
    caller (input) {
      return input.toUpperCase()
    }
  }
  const str = prettifyMetadata({
    log: { pid: '1234', hostname: 'bar', caller: 'baz', name: 'joe' },
    context: {
      customPrettifiers: prettifiers,
      colorizer: { colors: {} }
    }
  })
  t.assert.strictEqual(str, '(JOE/1234__ on BAR) <BAZ>')
})

test('uses colorizer from passed context to colorize metadata', t => {
  const prettifiers = {
    name (input, _key, _log, { colors }) {
      return colors.blue(input)
    },
    pid (input, _key, _log, { colors }) {
      return colors.red(input)
    },
    hostname (input, _key, _log, { colors }) {
      return colors.green(input)
    },
    caller (input, _key, _log, { colors }) {
      return colors.cyan(input)
    }
  }
  const log = { name: 'foo', pid: '1234', hostname: 'bar', caller: 'baz' }
  const colorizer = getColorizer(true)
  const context = {
    customPrettifiers: prettifiers,
    colorizer
  }

  const result = prettifyMetadata({ log, context })

  const colorizedName = colorizer.colors.blue(log.name)
  const colorizedPid = colorizer.colors.red(log.pid)
  const colorizedHostname = colorizer.colors.green(log.hostname)
  const colorizedCaller = colorizer.colors.cyan(log.caller)
  const expected = `(${colorizedName}/${colorizedPid} on ${colorizedHostname}) <${colorizedCaller}>`

  t.assert.strictEqual(result, expected)
})
