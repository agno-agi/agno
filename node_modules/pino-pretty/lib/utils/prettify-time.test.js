'use strict'

process.env.TZ = 'UTC'

const { test } = require('node:test')
const prettifyTime = require('./prettify-time')
const {
  TIMESTAMP_KEY
} = require('../constants')
const context = {
  timestampKey: TIMESTAMP_KEY,
  translateTime: true,
  customPrettifiers: {}
}

test('returns `undefined` if `time` or `timestamp` not in log', t => {
  const str = prettifyTime({ log: {}, context })
  t.assert.strictEqual(str, undefined)
})

test('returns prettified formatted time from custom field', t => {
  const log = { customtime: 1554642900000 }
  let str = prettifyTime({
    log,
    context: {
      ...context,
      timestampKey: 'customtime'
    }
  })
  t.assert.strictEqual(str, '[13:15:00.000]')

  str = prettifyTime({
    log,
    context: {
      ...context,
      translateTime: false,
      timestampKey: 'customtime'
    }
  })
  t.assert.strictEqual(str, '[1554642900000]')
})

test('returns prettified formatted time', t => {
  let log = { time: 1554642900000 }
  let str = prettifyTime({
    log,
    context: {
      ...context
    }
  })
  t.assert.strictEqual(str, '[13:15:00.000]')

  log = { timestamp: 1554642900000 }
  str = prettifyTime({
    log,
    context: {
      ...context
    }
  })
  t.assert.strictEqual(str, '[13:15:00.000]')

  log = { time: '2019-04-07T09:15:00.000-04:00' }
  str = prettifyTime({
    log,
    context: {
      ...context
    }
  })
  t.assert.strictEqual(str, '[13:15:00.000]')

  log = { timestamp: '2019-04-07T09:15:00.000-04:00' }
  str = prettifyTime({
    log,
    context: {
      ...context
    }
  })
  t.assert.strictEqual(str, '[13:15:00.000]')

  log = { time: 1554642900000 }
  str = prettifyTime({
    log,
    context: {
      ...context,
      translateTime: 'd mmm yyyy H:MM'
    }
  })
  t.assert.strictEqual(str, '[7 Apr 2019 13:15]')

  log = { timestamp: 1554642900000 }
  str = prettifyTime({
    log,
    context: {
      ...context,
      translateTime: 'd mmm yyyy H:MM'
    }
  })
  t.assert.strictEqual(str, '[7 Apr 2019 13:15]')

  log = { time: '2019-04-07T09:15:00.000-04:00' }
  str = prettifyTime({
    log,
    context: {
      ...context,
      translateTime: 'd mmm yyyy H:MM'
    }
  })
  t.assert.strictEqual(str, '[7 Apr 2019 13:15]')

  log = { timestamp: '2019-04-07T09:15:00.000-04:00' }
  str = prettifyTime({
    log,
    context: {
      ...context,
      translateTime: 'd mmm yyyy H:MM'
    }
  })
  t.assert.strictEqual(str, '[7 Apr 2019 13:15]')
})

test('passes through value', t => {
  let log = { time: 1554642900000 }
  let str = prettifyTime({
    log,
    context: {
      ...context,
      translateTime: undefined
    }
  })
  t.assert.strictEqual(str, '[1554642900000]')

  log = { timestamp: 1554642900000 }
  str = prettifyTime({
    log,
    context: {
      ...context,
      translateTime: undefined
    }
  })
  t.assert.strictEqual(str, '[1554642900000]')

  log = { time: '2019-04-07T09:15:00.000-04:00' }
  str = prettifyTime({
    log,
    context: {
      ...context,
      translateTime: undefined
    }
  })
  t.assert.strictEqual(str, '[2019-04-07T09:15:00.000-04:00]')

  log = { timestamp: '2019-04-07T09:15:00.000-04:00' }
  str = prettifyTime({
    log,
    context: {
      ...context,
      translateTime: undefined
    }
  })
  t.assert.strictEqual(str, '[2019-04-07T09:15:00.000-04:00]')
})

test('handles the 0 timestamp', t => {
  let log = { time: 0 }
  let str = prettifyTime({
    log,
    context: {
      ...context,
      translateTime: undefined
    }
  })
  t.assert.strictEqual(str, '[0]')

  log = { timestamp: 0 }
  str = prettifyTime({
    log,
    context: {
      ...context,
      translateTime: undefined
    }
  })
  t.assert.strictEqual(str, '[0]')
})

test('works with epoch as a number or string', (t) => {
  t.plan(3)
  const epoch = 1522431328992
  const asNumber = prettifyTime({
    log: { time: epoch, msg: 'foo' },
    context: {
      ...context,
      translateTime: true
    }
  })
  const asString = prettifyTime({
    log: { time: `${epoch}`, msg: 'foo' },
    context: {
      ...context,
      translateTime: true
    }
  })
  const invalid = prettifyTime({
    log: { time: '2 days ago', msg: 'foo' },
    context: {
      ...context,
      translateTime: true
    }
  })
  t.assert.strictEqual(asString, '[17:35:28.992]')
  t.assert.strictEqual(asNumber, '[17:35:28.992]')
  t.assert.strictEqual(invalid, '[2 days ago]')
})

test('uses custom prettifier', t => {
  const str = prettifyTime({
    log: { time: 0 },
    context: {
      ...context,
      customPrettifiers: {
        time () {
          return 'done'
        }
      }
    }
  })
  t.assert.strictEqual(str, 'done')
})
