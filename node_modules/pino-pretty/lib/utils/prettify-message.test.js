'use strict'

const { test } = require('node:test')
const prettifyMessage = require('./prettify-message')
const getColorizer = require('../colors')
const {
  LEVEL_KEY,
  LEVEL_LABEL
} = require('../constants')
const context = {
  colorizer: getColorizer(),
  levelKey: LEVEL_KEY,
  levelLabel: LEVEL_LABEL,
  messageKey: 'msg'
}

test('returns `undefined` if `messageKey` not found', t => {
  const str = prettifyMessage({ log: {}, context })
  t.assert.strictEqual(str, undefined)
})

test('returns `undefined` if `messageKey` not string', t => {
  const str = prettifyMessage({ log: { msg: {} }, context })
  t.assert.strictEqual(str, undefined)
})

test('returns non-colorized value for default colorizer', t => {
  const colorizer = getColorizer()
  const str = prettifyMessage({
    log: { msg: 'foo' },
    context: { ...context, colorizer }
  })
  t.assert.strictEqual(str, 'foo')
})

test('returns non-colorized value for alternate `messageKey`', t => {
  const str = prettifyMessage({
    log: { message: 'foo' },
    context: { ...context, messageKey: 'message' }
  })
  t.assert.strictEqual(str, 'foo')
})

test('returns colorized value for color colorizer', t => {
  const colorizer = getColorizer(true)
  const str = prettifyMessage({
    log: { msg: 'foo' },
    context: { ...context, colorizer }
  })
  t.assert.strictEqual(str, '\u001B[36mfoo\u001B[39m')
})

test('returns colorized value for color colorizer for alternate `messageKey`', t => {
  const colorizer = getColorizer(true)
  const str = prettifyMessage({
    log: { message: 'foo' },
    context: { ...context, messageKey: 'message', colorizer }
  })
  t.assert.strictEqual(str, '\u001B[36mfoo\u001B[39m')
})

test('returns message formatted by `messageFormat` option', t => {
  const str = prettifyMessage({
    log: { msg: 'foo', context: 'appModule' },
    context: { ...context, messageFormat: '{context} - {msg}' }
  })
  t.assert.strictEqual(str, 'appModule - foo')
})

test('returns message formatted by `messageFormat` option - missing prop', t => {
  const str = prettifyMessage({
    log: { context: 'appModule' },
    context: { ...context, messageFormat: '{context} - {msg}' }
  })
  t.assert.strictEqual(str, 'appModule - ')
})

test('returns message formatted by `messageFormat` option - levelLabel & useOnlyCustomProps false', t => {
  const str = prettifyMessage({
    log: { msg: 'foo', context: 'appModule', level: 30 },
    context: {
      ...context,
      messageFormat: '[{level}] {levelLabel} {context} - {msg}',
      customLevels: {}
    }
  })
  t.assert.strictEqual(str, '[30] INFO appModule - foo')
})

test('returns message formatted by `messageFormat` option - levelLabel & useOnlyCustomProps true', t => {
  const str = prettifyMessage({
    log: { msg: 'foo', context: 'appModule', level: 30 },
    context: {
      ...context,
      messageFormat: '[{level}] {levelLabel} {context} - {msg}',
      customLevels: { 30: 'CHECK' },
      useOnlyCustomProps: true
    }
  })
  t.assert.strictEqual(str, '[30] CHECK appModule - foo')
})

test('returns message formatted by `messageFormat` option - levelLabel & customLevels', t => {
  const str = prettifyMessage({
    log: { msg: 'foo', context: 'appModule', level: 123 },
    context: {
      ...context,
      messageFormat: '[{level}] {levelLabel} {context} - {msg}',
      customLevels: { 123: 'CUSTOM' }
    }
  })
  t.assert.strictEqual(str, '[123] CUSTOM appModule - foo')
})

test('returns message formatted by `messageFormat` option - levelLabel, customLevels & useOnlyCustomProps', t => {
  const str = prettifyMessage({
    log: { msg: 'foo', context: 'appModule', level: 123 },
    context: {
      ...context,
      messageFormat: '[{level}] {levelLabel} {context} - {msg}',
      customLevels: { 123: 'CUSTOM' },
      useOnlyCustomProps: true
    }
  })
  t.assert.strictEqual(str, '[123] CUSTOM appModule - foo')
})

test('returns message formatted by `messageFormat` option - levelLabel, customLevels & useOnlyCustomProps false', t => {
  const str = prettifyMessage({
    log: { msg: 'foo', context: 'appModule', level: 40 },
    context: {
      ...context,
      messageFormat: '[{level}] {levelLabel} {context} - {msg}',
      customLevels: { 123: 'CUSTOM' },
      useOnlyCustomProps: false
    }
  })
  t.assert.strictEqual(str, '[40] WARN appModule - foo')
})

test('`messageFormat` supports nested curly brackets', t => {
  const str = prettifyMessage({
    log: { level: 30 },
    context: {
      ...context,
      messageFormat: '{{level}}-{level}-{{level}-{level}}'
    }
  })
  t.assert.strictEqual(str, '{30}-30-{30-30}')
})

test('`messageFormat` supports nested object', t => {
  const str = prettifyMessage({
    log: { level: 30, request: { url: 'localhost/test' }, msg: 'foo' },
    context: {
      ...context,
      messageFormat: '{request.url} - param: {request.params.process} - {msg}'
    }
  })
  t.assert.strictEqual(str, 'localhost/test - param:  - foo')
})

test('`messageFormat` supports conditional blocks', t => {
  const str = prettifyMessage({
    log: { level: 30, req: { id: 'foo' } },
    context: {
      ...context,
      messageFormat: '{level} | {if req.id}({req.id}){end}{if msg}{msg}{end}'
    }
  })
  t.assert.strictEqual(str, '30 | (foo)')
})

test('`messageFormat` supports function definition', t => {
  const str = prettifyMessage({
    log: { level: 30, request: { url: 'localhost/test' }, msg: 'incoming request' },
    context: {
      ...context,
      messageFormat: (log, messageKey, levelLabel) => {
        let msg = log[messageKey]
        if (msg === 'incoming request') msg = `--> ${log.request.url}`
        return msg
      }
    }
  })
  t.assert.strictEqual(str, '--> localhost/test')
})

test('`messageFormat` supports function definition with colorizer object', t => {
  const colorizer = getColorizer(true)
  const str = prettifyMessage({
    log: { level: 30, request: { url: 'localhost/test' }, msg: 'incoming request' },
    context: {
      ...context,
      colorizer,
      messageFormat: (log, messageKey, levelLabel, { colors }) => {
        let msg = log[messageKey]
        if (msg === 'incoming request') msg = `--> ${colors.red(log.request.url)}`
        return msg
      }
    }
  })
  t.assert.strictEqual(str, '\u001B[36m--> \u001B[31mlocalhost/test\u001B[36m\u001B[39m')
})

test('`messageFormat` supports function definition with colorizer object when using custom colors', t => {
  const colorizer = getColorizer(true, [[30, 'brightGreen']], false)
  const str = prettifyMessage({
    log: { level: 30, request: { url: 'localhost/test' }, msg: 'incoming request' },
    context: {
      ...context,
      colorizer,
      messageFormat: (log, messageKey, levelLabel, { colors }) => {
        let msg = log[messageKey]
        if (msg === 'incoming request') msg = `--> ${colors.red(log.request.url)}`
        return msg
      }
    }
  })
  t.assert.strictEqual(str, '\u001B[36m--> \u001B[31mlocalhost/test\u001B[36m\u001B[39m')
})

test('`messageFormat` supports function definition with colorizer object when no color is supported', t => {
  const colorizer = getColorizer(false)
  const str = prettifyMessage({
    log: { level: 30, request: { url: 'localhost/test' }, msg: 'incoming request' },
    context: {
      ...context,
      colorizer,
      messageFormat: (log, messageKey, levelLabel, { colors }) => {
        let msg = log[messageKey]
        if (msg === 'incoming request') msg = `--> ${colors.red(log.request.url)}`
        return msg
      }
    }
  })
  t.assert.strictEqual(str, '--> localhost/test')
})
