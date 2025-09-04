'use strict'

const { test } = require('node:test')
const splitPropertyKey = require('./split-property-key')

test('splitPropertyKey does not change key', t => {
  const result = splitPropertyKey('data1')
  t.assert.deepStrictEqual(result, ['data1'])
})

test('splitPropertyKey splits nested key', t => {
  const result = splitPropertyKey('data1.data2.data-3')
  t.assert.deepStrictEqual(result, ['data1', 'data2', 'data-3'])
})

test('splitPropertyKey splits nested keys ending with a dot', t => {
  const result = splitPropertyKey('data1.data2.data-3.')
  t.assert.deepStrictEqual(result, ['data1', 'data2', 'data-3'])
})

test('splitPropertyKey splits nested escaped key', t => {
  const result = splitPropertyKey('logging\\.domain\\.corp/operation.foo.bar-2')
  t.assert.deepStrictEqual(result, ['logging.domain.corp/operation', 'foo', 'bar-2'])
})

test('splitPropertyKey splits nested escaped key with special characters', t => {
  const result = splitPropertyKey('logging\\.domain\\.corp/operation.!\t@#$%^&*()_+=-<>.bar\\.2')
  t.assert.deepStrictEqual(result, ['logging.domain.corp/operation', '!\t@#$%^&*()_+=-<>', 'bar.2'])
})
