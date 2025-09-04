'use strict'

const { test } = require('node:test')
const { rimraf } = require('rimraf')
const fs = require('node:fs')
const { join } = require('node:path')

const buildSafeSonicBoom = require('./build-safe-sonic-boom')

const file = () => {
  const dest = join(__dirname, `${process.pid}-${process.hrtime().toString()}`)
  const fd = fs.openSync(dest, 'w')
  return { dest, fd }
}

test('should not write when error emitted and code is "EPIPE"', t => {
  t.plan(1)

  const { fd, dest } = file()
  const stream = buildSafeSonicBoom({ sync: true, fd, mkdir: true })
  t.after(() => rimraf(dest))

  stream.emit('error', { code: 'EPIPE' })
  stream.write('will not work')

  const dataFile = fs.readFileSync(dest)
  t.assert.strictEqual(dataFile.length, 0)
})

test('should stream.write works when error code is not "EPIPE"', t => {
  t.plan(3)
  const { fd, dest } = file()
  const stream = buildSafeSonicBoom({ sync: true, fd, mkdir: true })

  t.after(() => rimraf(dest))

  stream.on('error', () => t.assert.ok('error emitted'))

  stream.emit('error', 'fake error description')

  t.assert.ok(stream.write('will work'))

  const dataFile = fs.readFileSync(dest)
  t.assert.strictEqual(dataFile.toString(), 'will work')
})

test('cover setupOnExit', async t => {
  t.plan(3)
  const { fd, dest } = file()
  const stream = buildSafeSonicBoom({ sync: false, fd, mkdir: true })

  t.after(() => rimraf(dest))

  stream.on('error', () => t.assert.ok('error emitted'))
  stream.emit('error', 'fake error description')

  t.assert.ok(stream.write('will work'))

  await watchFileCreated(dest)

  const dataFile = fs.readFileSync(dest)
  t.assert.strictEqual(dataFile.toString(), 'will work')
})

function watchFileCreated (filename) {
  return new Promise((resolve, reject) => {
    const TIMEOUT = 2000
    const INTERVAL = 100
    const threshold = TIMEOUT / INTERVAL
    let counter = 0
    const interval = setInterval(() => {
      // On some CI runs file is created but not filled
      if (fs.existsSync(filename) && fs.statSync(filename).size !== 0) {
        clearInterval(interval)
        resolve()
      } else if (counter <= threshold) {
        counter++
      } else {
        clearInterval(interval)
        reject(new Error(`${filename} was not created.`))
      }
    }, INTERVAL)
  })
}
