'use strict'

const { describe, test } = require('node:test')
const filterLog = require('./filter-log')

const context = {
  includeKeys: undefined,
  ignoreKeys: undefined
}
const logData = {
  level: 30,
  time: 1522431328992,
  data1: {
    data2: { 'data-3': 'bar' },
    error: new Error('test')
  }
}
const logData2 = Object.assign({
  'logging.domain.corp/operation': {
    id: 'foo',
    producer: 'bar'
  }
}, logData)

describe('#filterLog with an ignoreKeys option', () => {
  test('filterLog removes single entry', t => {
    const result = filterLog({
      log: logData,
      context: {
        ...context,
        ignoreKeys: ['data1.data2.data-3']
      }
    })
    t.assert.deepStrictEqual(result, { level: 30, time: 1522431328992, data1: { data2: { }, error: new Error('test') } })
  })

  test('filterLog removes multiple entries', t => {
    const result = filterLog({
      log: logData,
      context: {
        ...context,
        ignoreKeys: ['time', 'data1']
      }
    })
    t.assert.deepStrictEqual(result, { level: 30 })
  })

  test('filterLog keeps error instance', t => {
    const result = filterLog({
      log: logData,
      context: {
        ...context,
        ignoreKeys: []
      }
    })
    t.assert.strictEqual(logData.data1.error, result.data1.error)
  })

  test('filterLog removes entry with escape sequence', t => {
    const result = filterLog({
      log: logData2,
      context: {
        ...context,
        ignoreKeys: ['data1', 'logging\\.domain\\.corp/operation']
      }
    })
    t.assert.deepStrictEqual(result, { level: 30, time: 1522431328992 })
  })

  test('filterLog removes entry with escape sequence nested', t => {
    const result = filterLog({
      log: logData2,
      context: {
        ...context,
        ignoreKeys: ['data1', 'logging\\.domain\\.corp/operation.producer']
      }
    })
    t.assert.deepStrictEqual(result, { level: 30, time: 1522431328992, 'logging.domain.corp/operation': { id: 'foo' } })
  })
})

for (const ignoreKeys of [
  undefined,
  ['level'],
  ['level', 'data1.data2.data-3']
]) {
  describe(`#filterLog with an includeKeys option when the ignoreKeys being ${ignoreKeys}`, () => {
    test('filterLog include nothing', t => {
      const result = filterLog({
        log: logData,
        context: {
          ...context,
          ignoreKeys,
          includeKeys: []
        }
      })
      t.assert.deepStrictEqual(result, {})
    })

    test('filterLog include single entry', t => {
      const result = filterLog({
        log: logData,
        context: {
          ...context,
          ignoreKeys,
          includeKeys: ['time']
        }
      })
      t.assert.deepStrictEqual(result, { time: 1522431328992 })
    })

    test('filterLog include multiple entries', t => {
      const result = filterLog({
        log: logData,
        context: {
          ...context,
          ignoreKeys,
          includeKeys: ['time', 'data1']
        }
      })
      t.assert.deepStrictEqual(result, {
        time: 1522431328992,
        data1: {
          data2: { 'data-3': 'bar' },
          error: new Error('test')
        }
      })
    })
  })
}

describe('#filterLog with circular references', () => {
  const logData = {
    level: 30,
    time: 1522431328992,
    data1: 'test'
  }
  logData.circular = logData

  test('filterLog removes single entry', t => {
    const result = filterLog({
      log: logData,
      context: {
        ...context,
        ignoreKeys: ['data1']
      }
    })

    t.assert.deepStrictEqual(result.circular.level, result.level)
    t.assert.deepStrictEqual(result.circular.time, result.time)

    delete result.circular
    t.assert.deepStrictEqual(result, { level: 30, time: 1522431328992 })
  })

  test('filterLog includes single entry', t => {
    const result = filterLog({
      log: logData,
      context: {
        ...context,
        includeKeys: ['data1']
      }
    })

    t.assert.deepStrictEqual(result, { data1: 'test' })
  })

  test('filterLog includes circular keys', t => {
    const result = filterLog({
      log: logData,
      context: {
        ...context,
        includeKeys: ['level', 'circular']
      }
    })

    t.assert.deepStrictEqual(result.circular.level, logData.level)
    t.assert.deepStrictEqual(result.circular.time, logData.time)

    delete result.circular
    t.assert.deepStrictEqual(result, { level: 30 })
  })
})
