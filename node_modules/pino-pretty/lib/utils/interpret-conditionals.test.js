'use strict'

const { test } = require('node:test')
const { createCopier } = require('fast-copy')
const fastCopy = createCopier({})
const interpretConditionals = require('./interpret-conditionals')

const logData = {
  level: 30,
  data1: {
    data2: 'bar'
  },
  msg: 'foo'
}

test('interpretConditionals translates if / else statement to found property value', t => {
  const log = fastCopy(logData)
  t.assert.strictEqual(interpretConditionals('{level} - {if data1.data2}{data1.data2}{end}', log), '{level} - bar')
})

test('interpretConditionals translates if / else statement to found property value and leave unmatched property key untouched', t => {
  const log = fastCopy(logData)
  t.assert.strictEqual(interpretConditionals('{level} - {if data1.data2}{data1.data2} ({msg}){end}', log), '{level} - bar ({msg})')
})

test('interpretConditionals removes non-terminated if statements', t => {
  const log = fastCopy(logData)
  t.assert.strictEqual(interpretConditionals('{level} - {if data1.data2}{data1.data2}', log), '{level} - {data1.data2}')
})

test('interpretConditionals removes floating end statements', t => {
  const log = fastCopy(logData)
  t.assert.strictEqual(interpretConditionals('{level} - {data1.data2}{end}', log), '{level} - {data1.data2}')
})

test('interpretConditionals removes floating end statements within translated if / end statements', t => {
  const log = fastCopy(logData)
  t.assert.strictEqual(interpretConditionals('{level} - {if msg}({msg}){end}{end}', log), '{level} - (foo)')
})

test('interpretConditionals removes if / end blocks if existent condition key does not match existent property key', t => {
  const log = fastCopy(logData)
  t.assert.strictEqual(interpretConditionals('{level}{if msg}{data1.data2}{end}', log), '{level}')
})

test('interpretConditionals removes if / end blocks if non-existent condition key does not match existent property key', t => {
  const log = fastCopy(logData)
  t.assert.strictEqual(interpretConditionals('{level}{if foo}{msg}{end}', log), '{level}')
})

test('interpretConditionals removes if / end blocks if existent condition key does not match non-existent property key', t => {
  const log = fastCopy(logData)
  t.assert.strictEqual(interpretConditionals('{level}{if msg}{foo}{end}', log), '{level}')
})

test('interpretConditionals removes if / end blocks if non-existent condition key does not match non-existent property key', t => {
  const log = fastCopy(logData)
  t.assert.strictEqual(interpretConditionals('{level}{if foo}{bar}{end}', log), '{level}')
})

test('interpretConditionals removes if / end blocks if nested condition key does not match property key', t => {
  const log = fastCopy(logData)
  t.assert.strictEqual(interpretConditionals('{level}{if data1.msg}{data1.data2}{end}', log), '{level}')
})

test('interpretConditionals removes nested if / end statement blocks', t => {
  const log = fastCopy(logData)
  t.assert.strictEqual(interpretConditionals('{if msg}{if data1.data2}{msg}{data1.data2}{end}{end}', log), 'foo{data1.data2}')
})
