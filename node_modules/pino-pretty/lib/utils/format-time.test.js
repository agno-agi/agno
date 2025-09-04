'use strict'

process.env.TZ = 'UTC'

const { test } = require('node:test')
const formatTime = require('./format-time')

const dateStr = '2019-04-06T13:30:00.000-04:00'
const epoch = new Date(dateStr)
const epochMS = epoch.getTime()

test('passes through epoch if `translateTime` is `false`', t => {
  const formattedTime = formatTime(epochMS)
  t.assert.strictEqual(formattedTime, epochMS)
})

test('passes through epoch if date is invalid', t => {
  const input = 'this is not a date'
  const formattedTime = formatTime(input, true)
  t.assert.strictEqual(formattedTime, input)
})

test('translates epoch milliseconds if `translateTime` is `true`', t => {
  const formattedTime = formatTime(epochMS, true)
  t.assert.strictEqual(formattedTime, '17:30:00.000')
})

test('translates epoch milliseconds to UTC string given format', t => {
  const formattedTime = formatTime(epochMS, 'd mmm yyyy H:MM')
  t.assert.strictEqual(formattedTime, '6 Apr 2019 17:30')
})

test('translates epoch milliseconds to SYS:STANDARD', t => {
  const formattedTime = formatTime(epochMS, 'SYS:STANDARD')
  t.assert.match(formattedTime, /\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} [-+]?\d{4}/)
})

test('translates epoch milliseconds to SYS:<FORMAT>', t => {
  const formattedTime = formatTime(epochMS, 'SYS:d mmm yyyy H:MM')
  t.assert.match(formattedTime, /\d{1} \w{3} \d{4} \d{1,2}:\d{2}/)
})

test('passes through date string if `translateTime` is `false`', t => {
  const formattedTime = formatTime(dateStr)
  t.assert.strictEqual(formattedTime, dateStr)
})

test('translates date string if `translateTime` is `true`', t => {
  const formattedTime = formatTime(dateStr, true)
  t.assert.strictEqual(formattedTime, '17:30:00.000')
})

test('translates date string to UTC string given format', t => {
  const formattedTime = formatTime(dateStr, 'd mmm yyyy H:MM')
  t.assert.strictEqual(formattedTime, '6 Apr 2019 17:30')
})

test('translates date string to SYS:STANDARD', t => {
  const formattedTime = formatTime(dateStr, 'SYS:STANDARD')
  t.assert.match(formattedTime, /\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} [-+]?\d{4}/)
})

test('translates date string to UTC:<FORMAT>', t => {
  const formattedTime = formatTime(dateStr, 'UTC:d mmm yyyy H:MM')
  t.assert.strictEqual(formattedTime, '6 Apr 2019 17:30')
})

test('translates date string to SYS:<FORMAT>', t => {
  const formattedTime = formatTime(dateStr, 'SYS:d mmm yyyy H:MM')
  t.assert.match(formattedTime, /\d{1} \w{3} \d{4} \d{1,2}:\d{2}/)
})
