'use strict'

const { test } = require('node:test')
const getColorizer = require('./colors')

const testDefaultColorizer = getColorizer => t => {
  const colorizer = getColorizer()
  let colorized = colorizer(10)
  t.assert.strictEqual(colorized, 'TRACE')

  colorized = colorizer(20)
  t.assert.strictEqual(colorized, 'DEBUG')

  colorized = colorizer(30)
  t.assert.strictEqual(colorized, 'INFO')

  colorized = colorizer(40)
  t.assert.strictEqual(colorized, 'WARN')

  colorized = colorizer(50)
  t.assert.strictEqual(colorized, 'ERROR')

  colorized = colorizer(60)
  t.assert.strictEqual(colorized, 'FATAL')

  colorized = colorizer(900)
  t.assert.strictEqual(colorized, 'USERLVL')

  colorized = colorizer('info')
  t.assert.strictEqual(colorized, 'INFO')

  colorized = colorizer('use-default')
  t.assert.strictEqual(colorized, 'USERLVL')

  colorized = colorizer.message('foo')
  t.assert.strictEqual(colorized, 'foo')

  colorized = colorizer.greyMessage('foo')
  t.assert.strictEqual(colorized, 'foo')
}

const testColoringColorizer = getColorizer => t => {
  const colorizer = getColorizer(true)
  let colorized = colorizer(10)
  t.assert.strictEqual(colorized, '\u001B[90mTRACE\u001B[39m')

  colorized = colorizer(20)
  t.assert.strictEqual(colorized, '\u001B[34mDEBUG\u001B[39m')

  colorized = colorizer(30)
  t.assert.strictEqual(colorized, '\u001B[32mINFO\u001B[39m')

  colorized = colorizer(40)
  t.assert.strictEqual(colorized, '\u001B[33mWARN\u001B[39m')

  colorized = colorizer(50)
  t.assert.strictEqual(colorized, '\u001B[31mERROR\u001B[39m')

  colorized = colorizer(60)
  t.assert.strictEqual(colorized, '\u001B[41mFATAL\u001B[49m')

  colorized = colorizer(900)
  t.assert.strictEqual(colorized, '\u001B[37mUSERLVL\u001B[39m')

  colorized = colorizer('info')
  t.assert.strictEqual(colorized, '\u001B[32mINFO\u001B[39m')

  colorized = colorizer('use-default')
  t.assert.strictEqual(colorized, '\u001B[37mUSERLVL\u001B[39m')

  colorized = colorizer.message('foo')
  t.assert.strictEqual(colorized, '\u001B[36mfoo\u001B[39m')

  colorized = colorizer.greyMessage('foo')
  t.assert.strictEqual(colorized, '\u001B[90mfoo\u001B[39m')
}

const testCustomColoringColorizer = getColorizer => t => {
  const customLevels = {
    0: 'INFO',
    1: 'ERR',
    default: 'USERLVL'
  }
  const customLevelNames = {
    info: 0,
    err: 1
  }
  const customColors = [
    [0, 'not-a-color'],
    [1, 'red']
  ]
  const opts = {
    customLevels,
    customLevelNames
  }

  const colorizer = getColorizer(true, customColors)
  const colorizerWithCustomPropUse = getColorizer(true, customColors, true)
  let colorized = colorizer(1, opts)
  t.assert.strictEqual(colorized, '\u001B[31mERR\u001B[39m')

  colorized = colorizer(0, opts)
  t.assert.strictEqual(colorized, '\u001B[37mINFO\u001B[39m')

  colorized = colorizer(900)
  t.assert.strictEqual(colorized, '\u001B[37mUSERLVL\u001B[39m')

  colorized = colorizer('err', opts)
  t.assert.strictEqual(colorized, '\u001B[31mERR\u001B[39m')

  colorized = colorizer('info', opts)
  t.assert.strictEqual(colorized, '\u001B[37mINFO\u001B[39m')

  colorized = colorizer('use-default')
  t.assert.strictEqual(colorized, '\u001B[37mUSERLVL\u001B[39m')

  colorized = colorizer(40, opts)
  t.assert.strictEqual(colorized, '\u001B[33mWARN\u001B[39m')

  colorized = colorizerWithCustomPropUse(50, opts)
  t.assert.strictEqual(colorized, '\u001B[37mUSERLVL\u001B[39m')
}

test('returns default colorizer - private export', testDefaultColorizer(getColorizer))
test('returns colorizing colorizer - private export', testColoringColorizer(getColorizer))
test('returns custom colorizing colorizer - private export', testCustomColoringColorizer(getColorizer))

test('custom props defaults to standard levels', t => {
  const colorizer = getColorizer(true, [], true)
  const colorized = colorizer('info')
  t.assert.strictEqual(colorized, '\u001B[37mINFO\u001B[39m')
})
