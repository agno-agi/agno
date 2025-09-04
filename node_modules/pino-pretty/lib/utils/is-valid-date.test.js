'use strict'

process.env.TZ = 'UTC'

const { test } = require('node:test')
const isValidDate = require('./is-valid-date')

test('returns true for valid dates', t => {
  t.assert.strictEqual(isValidDate(new Date()), true)
})

test('returns false for non-dates and invalid dates', t => {
  t.plan(2)
  t.assert.strictEqual(isValidDate('20210621'), false)
  t.assert.strictEqual(isValidDate(new Date('2021-41-99')), false)
})
