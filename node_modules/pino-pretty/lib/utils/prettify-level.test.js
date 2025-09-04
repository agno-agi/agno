'use strict'

const { test } = require('node:test')
const prettifyLevel = require('./prettify-level')
const getColorizer = require('../colors')
const getLevelLabelData = require('./get-level-label-data')
const {
  LEVEL_KEY
} = require('../constants')

const context = {
  colorizer: getColorizer(),
  customLevelNames: undefined,
  customLevels: undefined,
  levelKey: LEVEL_KEY,
  customPrettifiers: undefined,
  getLevelLabelData: getLevelLabelData(false, {}, {})
}

test('returns `undefined` for unknown level', t => {
  const colorized = prettifyLevel({
    log: {},
    context: {
      ...context
    }
  })
  t.assert.strictEqual(colorized, undefined)
})

test('returns non-colorized value for default colorizer', t => {
  const log = {
    level: 30
  }
  const colorized = prettifyLevel({
    log,
    context: {
      ...context
    }
  })
  t.assert.strictEqual(colorized, 'INFO')
})

test('returns colorized value for color colorizer', t => {
  const log = {
    level: 30
  }
  const colorizer = getColorizer(true)
  const colorized = prettifyLevel({
    log,
    context: {
      ...context,
      colorizer
    }
  })
  t.assert.strictEqual(colorized, '\u001B[32mINFO\u001B[39m')
})

test('passes output through provided prettifier', t => {
  const log = {
    level: 30
  }
  const colorized = prettifyLevel({
    log,
    context: {
      ...context,
      customPrettifiers: { level () { return 'modified' } }
    }
  })
  t.assert.strictEqual(colorized, 'modified')
})
