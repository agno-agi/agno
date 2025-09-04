'use strict'

const { test } = require('node:test')
const { createCopier } = require('fast-copy')
const fastCopy = createCopier({})
const deleteLogProperty = require('./delete-log-property')

const logData = {
  level: 30,
  data1: {
    data2: { 'data-3': 'bar' }
  }
}

test('deleteLogProperty deletes property of depth 1', t => {
  const log = fastCopy(logData)
  deleteLogProperty(log, 'data1')
  t.assert.deepStrictEqual(log, { level: 30 })
})

test('deleteLogProperty deletes property of depth 2', t => {
  const log = fastCopy(logData)
  deleteLogProperty(log, 'data1.data2')
  t.assert.deepStrictEqual(log, { level: 30, data1: { } })
})

test('deleteLogProperty deletes property of depth 3', t => {
  const log = fastCopy(logData)
  deleteLogProperty(log, 'data1.data2.data-3')
  t.assert.deepStrictEqual(log, { level: 30, data1: { data2: { } } })
})
