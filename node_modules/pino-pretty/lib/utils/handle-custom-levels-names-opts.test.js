'use strict'

const { test } = require('node:test')
const match = require('@jsumners/assert-match')
const handleCustomLevelsNamesOpts = require('./handle-custom-levels-names-opts')

test('returns a empty object `{}` for undefined parameter', t => {
  const handledCustomLevelNames = handleCustomLevelsNamesOpts()
  t.assert.deepStrictEqual(handledCustomLevelNames, {})
})

test('returns a empty object `{}` for unknown parameter', t => {
  const handledCustomLevelNames = handleCustomLevelsNamesOpts(123)
  t.assert.deepStrictEqual(handledCustomLevelNames, {})
})

test('returns a filled object for string parameter', t => {
  const handledCustomLevelNames = handleCustomLevelsNamesOpts('ok:10,warn:20,error:35')
  match(handledCustomLevelNames, {
    ok: 10,
    warn: 20,
    error: 35
  }, t)
})

test('returns a filled object for object parameter', t => {
  const handledCustomLevelNames = handleCustomLevelsNamesOpts({
    ok: 10,
    warn: 20,
    error: 35
  })
  match(handledCustomLevelNames, {
    ok: 10,
    warn: 20,
    error: 35
  }, t)
})

test('defaults missing level num to first index', t => {
  const result = handleCustomLevelsNamesOpts('ok:10,info')
  match(result, {
    ok: 10,
    info: 1
  }, t)
})
