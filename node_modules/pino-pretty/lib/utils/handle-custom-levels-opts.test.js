'use strict'

const { test } = require('node:test')
const handleCustomLevelsOpts = require('./handle-custom-levels-opts')

test('returns a empty object `{}` for undefined parameter', t => {
  const handledCustomLevel = handleCustomLevelsOpts()
  t.assert.deepStrictEqual(handledCustomLevel, {})
})

test('returns a empty object `{}` for unknown parameter', t => {
  const handledCustomLevel = handleCustomLevelsOpts(123)
  t.assert.deepStrictEqual(handledCustomLevel, {})
})

test('returns a filled object for string parameter', t => {
  const handledCustomLevel = handleCustomLevelsOpts('ok:10,warn:20,error:35')
  t.assert.deepStrictEqual(handledCustomLevel, {
    10: 'OK',
    20: 'WARN',
    35: 'ERROR',
    default: 'USERLVL'
  })
})

test('returns a filled object for object parameter', t => {
  const handledCustomLevel = handleCustomLevelsOpts({
    ok: 10,
    warn: 20,
    error: 35
  })
  t.assert.deepStrictEqual(handledCustomLevel, {
    10: 'OK',
    20: 'WARN',
    35: 'ERROR',
    default: 'USERLVL'
  })
})

test('defaults missing level num to first index', t => {
  const result = handleCustomLevelsOpts('ok:10,info')
  t.assert.deepStrictEqual(result, {
    10: 'OK',
    1: 'INFO',
    default: 'USERLVL'
  })
})
