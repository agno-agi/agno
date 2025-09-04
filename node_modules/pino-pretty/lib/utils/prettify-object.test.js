'use strict'

const { test } = require('node:test')
const colors = require('../colors')
const prettifyObject = require('./prettify-object')
const {
  ERROR_LIKE_KEYS
} = require('../constants')

const context = {
  EOL: '\n',
  IDENT: '    ',
  customPrettifiers: {},
  errorLikeObjectKeys: ERROR_LIKE_KEYS,
  objectColorizer: colors(),
  singleLine: false,
  colorizer: colors()
}

test('returns empty string if no properties present', t => {
  const str = prettifyObject({ log: {}, context })
  t.assert.strictEqual(str, '')
})

test('works with single level properties', t => {
  const str = prettifyObject({ log: { foo: 'bar' }, context })
  t.assert.strictEqual(str, '    foo: "bar"\n')
})

test('works with multiple level properties', t => {
  const str = prettifyObject({ log: { foo: { bar: 'baz' } }, context })
  t.assert.strictEqual(str, '    foo: {\n      "bar": "baz"\n    }\n')
})

test('skips specified keys', t => {
  const str = prettifyObject({
    log: { foo: 'bar', hello: 'world' },
    skipKeys: ['foo'],
    context
  })
  t.assert.strictEqual(str, '    hello: "world"\n')
})

test('ignores predefined keys', t => {
  const str = prettifyObject({ log: { foo: 'bar', pid: 12345 }, context })
  t.assert.strictEqual(str, '    foo: "bar"\n')
})

test('ignores escaped backslashes in string values', t => {
  const str = prettifyObject({ log: { foo_regexp: '\\[^\\w\\s]\\' }, context })
  t.assert.strictEqual(str, '    foo_regexp: "\\[^\\w\\s]\\"\n')
})

test('ignores escaped backslashes in string values (singleLine option)', t => {
  const str = prettifyObject({
    log: { foo_regexp: '\\[^\\w\\s]\\' },
    context: {
      ...context,
      singleLine: true
    }
  })
  t.assert.strictEqual(str, '{"foo_regexp":"\\[^\\w\\s]\\"}\n')
})

test('works with error props', t => {
  const err = Error('Something went wrong')
  const serializedError = {
    message: err.message,
    stack: err.stack
  }
  const str = prettifyObject({ log: { error: serializedError }, context })
  t.assert.ok(str.startsWith('    error:'))
  t.assert.ok(str.includes('     "message": "Something went wrong",'))
  t.assert.ok(str.includes('         Error: Something went wrong'))
})

test('customPrettifiers gets applied', t => {
  const customPrettifiers = {
    foo: v => v.toUpperCase()
  }
  const str = prettifyObject({
    log: { foo: 'foo' },
    context: {
      ...context,
      customPrettifiers
    }
  })
  t.assert.strictEqual(str.startsWith('    foo: FOO'), true)
})

test('skips lines omitted by customPrettifiers', t => {
  const customPrettifiers = {
    foo: () => { return undefined }
  }
  const str = prettifyObject({
    log: { foo: 'foo', bar: 'bar' },
    context: {
      ...context,
      customPrettifiers
    }
  })
  t.assert.strictEqual(str.includes('bar: "bar"'), true)
  t.assert.strictEqual(str.includes('foo: "foo"'), false)
})

test('joined lines omits starting eol', t => {
  const str = prettifyObject({
    log: { msg: 'doing work', calls: ['step 1', 'step 2', 'step 3'], level: 30 },
    context: {
      ...context,
      IDENT: '',
      customPrettifiers: {
        calls: val => '\n' + val.map(it => '  ' + it).join('\n')
      }
    }
  })
  t.assert.strictEqual(str, [
    'msg: "doing work"',
    'calls:',
    '  step 1',
    '  step 2',
    '  step 3',
    ''
  ].join('\n'))
})

test('errors skips prettifiers', t => {
  const customPrettifiers = {
    err: () => { return 'is_err' }
  }
  const str = prettifyObject({
    log: { err: Error('boom') },
    context: {
      ...context,
      customPrettifiers
    }
  })
  t.assert.strictEqual(str.includes('err: is_err'), true)
})

test('errors skips prettifying if no lines are present', t => {
  const customPrettifiers = {
    err: () => { return undefined }
  }
  const str = prettifyObject({
    log: { err: Error('boom') },
    context: {
      ...context,
      customPrettifiers
    }
  })
  t.assert.strictEqual(str, '')
})

test('works with single level properties', t => {
  const colorizer = colors(true)
  const str = prettifyObject({
    log: { foo: 'bar' },
    context: {
      ...context,
      objectColorizer: colorizer,
      colorizer
    }
  })
  t.assert.strictEqual(str, `    ${colorizer.colors.magenta('foo')}: "bar"\n`)
})
