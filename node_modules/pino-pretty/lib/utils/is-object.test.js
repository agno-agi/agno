'use strict'

const { test } = require('node:test')
const isObject = require('./is-object')

test('returns correct answer', t => {
  t.assert.strictEqual(isObject({}), true)
  t.assert.strictEqual(isObject([]), false)
  t.assert.strictEqual(isObject(42), false)
})
