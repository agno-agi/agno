'use strict'

const { test } = require('node:test')
const createDate = require('./create-date')

const wanted = 1624450038567

test('accepts arguments the Date constructor would accept', t => {
  t.plan(2)
  t.assert.strictEqual(createDate(1624450038567).getTime(), wanted)
  t.assert.strictEqual(createDate('2021-06-23T12:07:18.567Z').getTime(), wanted)
})

test('accepts epoch as a string', t => {
  // If Date() accepts this argument, the createDate function is not needed
  // and can be replaced with Date()
  t.plan(2)
  t.assert.notEqual(new Date('16244500385-67').getTime(), wanted)
  t.assert.strictEqual(createDate('1624450038567').getTime(), wanted)
})
