'use strict'

const { test } = require('node:test')
const getPropertyValue = require('./get-property-value')

test('getPropertyValue returns the value of the property', t => {
  const result = getPropertyValue({
    foo: 'bar'
  }, 'foo')
  t.assert.strictEqual(result, 'bar')
})

test('getPropertyValue returns the value of the nested property', t => {
  const result = getPropertyValue({ extra: { foo: { value: 'bar' } } }, 'extra.foo.value')
  t.assert.strictEqual(result, 'bar')
})

test('getPropertyValue returns the value of the nested property using the array of nested property keys', t => {
  const result = getPropertyValue({ extra: { foo: { value: 'bar' } } }, ['extra', 'foo', 'value'])
  t.assert.strictEqual(result, 'bar')
})

test('getPropertyValue returns undefined for non-existing properties', t => {
  const result = getPropertyValue({ extra: { foo: { value: 'bar' } } }, 'extra.foo.value-2')
  t.assert.strictEqual(result, undefined)
})

test('getPropertyValue returns undefined for non-existing properties using the array of nested property keys', t => {
  const result = getPropertyValue({ extra: { foo: { value: 'bar' } } }, ['extra', 'foo', 'value-2'])
  t.assert.strictEqual(result, undefined)
})
