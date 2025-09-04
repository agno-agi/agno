'use strict'

process.env.TZ = 'UTC'

const path = require('node:path')
const { spawn } = require('node:child_process')
const { describe, test } = require('node:test')
const { once } = require('./helper')

const bin = require.resolve(path.join(__dirname, '..', 'bin.js'))
const epoch = 1522431328992
const logLine = '{"level":30,"time":1522431328992,"msg":"hello world","pid":42,"hostname":"foo"}\n'
const env = { TERM: 'dumb', TZ: 'UTC' }
const formattedEpoch = '17:35:28.992'

describe('cli', () => {
  test('does basic reformatting', async (t) => {
    t.plan(1)
    const child = spawn(process.argv[0], [bin], { env })
    child.on('error', t.assert.fail)
    const endPromise = once(child.stdout, 'data', (data) => {
      t.assert.strictEqual(data.toString(), `[${formattedEpoch}] INFO (42): hello world\n`)
    })
    child.stdin.write(logLine)
    await endPromise
    t.after(() => child.kill())
  })

  for (const optionName of ['--levelFirst', '-l']) {
    test(`flips epoch and level via ${optionName}`, async (t) => {
      t.plan(1)
      const child = spawn(process.argv[0], [bin, optionName], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `INFO [${formattedEpoch}] (42): hello world\n`)
      })
      child.stdin.write(logLine)
      await endPromise
      t.after(() => child.kill())
    })
  }

  for (const optionName of ['--translateTime', '-t']) {
    test(`translates time to default format via ${optionName}`, async (t) => {
      t.plan(1)
      const child = spawn(process.argv[0], [bin, optionName], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `[${formattedEpoch}] INFO (42): hello world\n`)
      })
      child.stdin.write(logLine)
      await endPromise
      t.after(() => child.kill())
    })
  }

  for (const optionName of ['--ignore', '-i']) {
    test('does ignore multiple keys', async (t) => {
      t.plan(1)
      const child = spawn(process.argv[0], [bin, optionName, 'pid,hostname'], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `[${formattedEpoch}] INFO: hello world\n`)
      })
      child.stdin.write(logLine)
      await endPromise
      t.after(() => child.kill())
    })
  }

  for (const optionName of ['--customLevels', '-x']) {
    test(`customize levels via ${optionName}`, async (t) => {
      t.plan(1)
      const logLine = '{"level":1,"time":1522431328992,"msg":"hello world","pid":42,"hostname":"foo"}\n'
      const child = spawn(process.argv[0], [bin, optionName, 'err:99,info:1'], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `[${formattedEpoch}] INFO (42): hello world\n`)
      })
      child.stdin.write(logLine)
      await endPromise
      t.after(() => child.kill())
    })

    test(`customize levels via ${optionName} without index`, async (t) => {
      t.plan(1)
      const logLine = '{"level":1,"time":1522431328992,"msg":"hello world","pid":42,"hostname":"foo"}\n'
      const child = spawn(process.argv[0], [bin, optionName, 'err:99,info'], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `[${formattedEpoch}] INFO (42): hello world\n`)
      })
      child.stdin.write(logLine)
      await endPromise
      t.after(() => child.kill())
    })

    test(`customize levels via ${optionName} with minimumLevel`, async (t) => {
      t.plan(1)
      const child = spawn(process.argv[0], [bin, '--minimumLevel', 'err', optionName, 'err:99,info:1'], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `[${formattedEpoch}] ERR (42): hello world\n`)
      })
      child.stdin.write('{"level":1,"time":1522431328992,"msg":"hello world","pid":42,"hostname":"foo"}\n')
      child.stdin.write('{"level":99,"time":1522431328992,"msg":"hello world","pid":42,"hostname":"foo"}\n')
      await endPromise
      t.after(() => child.kill())
    })

    test(`customize levels via ${optionName} with minimumLevel, customLevels and useOnlyCustomProps false`, async (t) => {
      t.plan(1)
      const child = spawn(process.argv[0], [bin, '--minimumLevel', 'custom', '--useOnlyCustomProps', 'false', optionName, 'custom:99,info:1'], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `[${formattedEpoch}] CUSTOM (42): hello world\n`)
      })
      child.stdin.write('{"level":1,"time":1522431328992,"msg":"hello world","pid":42,"hostname":"foo"}\n')
      child.stdin.write('{"level":99,"time":1522431328992,"msg":"hello world","pid":42,"hostname":"foo"}\n')
      await endPromise
      t.after(() => child.kill())
    })

    test(`customize levels via ${optionName} with minimumLevel, customLevels and useOnlyCustomProps true`, async (t) => {
      t.plan(1)
      const child = spawn(process.argv[0], [bin, '--minimumLevel', 'custom', '--useOnlyCustomProps', 'true', optionName, 'custom:99,info:1'], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `[${formattedEpoch}] CUSTOM (42): hello world\n`)
      })
      child.stdin.write('{"level":1,"time":1522431328992,"msg":"hello world","pid":42,"hostname":"foo"}\n')
      child.stdin.write('{"level":99,"time":1522431328992,"msg":"hello world","pid":42,"hostname":"foo"}\n')
      await endPromise
      t.after(() => child.kill())
    })
  }

  for (const optionName of ['--customColors', '-X']) {
    test(`customize levels via ${optionName}`, async (t) => {
      t.plan(1)
      const child = spawn(process.argv[0], [bin, optionName, 'info:blue,message:red'], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `[${formattedEpoch}] INFO (42): hello world\n`)
      })
      child.stdin.write(logLine)
      await endPromise
      t.after(() => child.kill())
    })

    test(`customize levels via ${optionName} with customLevels`, async (t) => {
      t.plan(1)
      const logLine = '{"level":1,"time":1522431328992,"msg":"hello world","pid":42,"hostname":"foo"}\n'
      const child = spawn(process.argv[0], [bin, '--customLevels', 'err:99,info', optionName, 'info:blue,message:red'], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `[${formattedEpoch}] INFO (42): hello world\n`)
      })
      child.stdin.write(logLine)
      await endPromise
      t.after(() => child.kill())
    })
  }

  for (const optionName of ['--useOnlyCustomProps', '-U']) {
    test(`customize levels via ${optionName} false and customColors`, async (t) => {
      t.plan(1)
      const child = spawn(process.argv[0], [bin, '--customColors', 'err:blue,info:red', optionName, 'false'], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `[${formattedEpoch}] INFO (42): hello world\n`)
      })
      child.stdin.write(logLine)
      await endPromise
      t.after(() => child.kill())
    })

    test(`customize levels via ${optionName} true and customColors`, async (t) => {
      t.plan(1)
      const child = spawn(process.argv[0], [bin, '--customColors', 'err:blue,info:red', optionName, 'true'], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `[${formattedEpoch}] INFO (42): hello world\n`)
      })
      child.stdin.write(logLine)
      await endPromise
      t.after(() => child.kill())
    })

    test(`customize levels via ${optionName} true and customLevels`, async (t) => {
      t.plan(1)
      const child = spawn(process.argv[0], [bin, '--customLevels', 'err:99,custom:30', optionName, 'true'], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `[${formattedEpoch}] CUSTOM (42): hello world\n`)
      })
      child.stdin.write(logLine)
      await endPromise
      t.after(() => child.kill())
    })

    test(`customize levels via ${optionName} true and no customLevels`, async (t) => {
      t.plan(1)
      const child = spawn(process.argv[0], [bin, optionName, 'true'], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `[${formattedEpoch}] INFO (42): hello world\n`)
      })
      child.stdin.write(logLine)
      await endPromise
      t.after(() => child.kill())
    })

    test(`customize levels via ${optionName} false and customLevels`, async (t) => {
      t.plan(1)
      const child = spawn(process.argv[0], [bin, '--customLevels', 'err:99,custom:25', optionName, 'false'], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `[${formattedEpoch}] INFO (42): hello world\n`)
      })
      child.stdin.write(logLine)
      await endPromise
      t.after(() => child.kill())
    })

    test(`customize levels via ${optionName} false and no customLevels`, async (t) => {
      t.plan(1)
      const child = spawn(process.argv[0], [bin, optionName, 'false'], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `[${formattedEpoch}] INFO (42): hello world\n`)
      })
      child.stdin.write(logLine)
      await endPromise
      t.after(() => child.kill())
    })
  }

  test('does ignore escaped keys', async (t) => {
    t.plan(1)
    const child = spawn(process.argv[0], [bin, '-i', 'log\\.domain\\.corp/foo'], { env })
    child.on('error', t.assert.fail)
    const endPromise = once(child.stdout, 'data', (data) => {
      t.assert.strictEqual(data.toString(), `[${formattedEpoch}] INFO: hello world\n`)
    })
    const logLine = '{"level":30,"time":1522431328992,"msg":"hello world","log.domain.corp/foo":"bar"}\n'
    child.stdin.write(logLine)
    await endPromise
    t.after(() => child.kill())
  })

  test('passes through stringified date as string', async (t) => {
    t.plan(1)
    const child = spawn(process.argv[0], [bin], { env })
    child.on('error', t.assert.fail)

    const date = JSON.stringify(new Date(epoch))

    const endPromise = once(child.stdout, 'data', (data) => {
      t.assert.strictEqual(data.toString(), date + '\n')
    })

    child.stdin.write(date)
    child.stdin.write('\n')

    await endPromise

    t.after(() => child.kill())
  })

  test('end stdin does not end the destination', async (t) => {
    t.plan(2)
    const child = spawn(process.argv[0], [bin], { env })
    child.on('error', t.assert.fail)

    const endPromise1 = once(child.stdout, 'data', (data) => {
      t.assert.strictEqual(data.toString(), 'aaa\n')
    })

    child.stdin.end('aaa\n')

    const endPromise2 = once(child, 'exit', (code) => {
      t.assert.strictEqual(code, 0)
    })
    await Promise.all([endPromise1, endPromise2])

    t.after(() => child.kill())
  })

  for (const optionName of ['--timestampKey', '-a']) {
    test(`uses specified timestamp key via ${optionName}`, async (t) => {
      t.plan(1)
      const child = spawn(process.argv[0], [bin, optionName, '@timestamp'], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `[${formattedEpoch}] INFO: hello world\n`)
      })
      const logLine = '{"level":30,"@timestamp":1522431328992,"msg":"hello world"}\n'
      child.stdin.write(logLine)
      await endPromise
      t.after(() => child.kill())
    })
  }

  for (const optionName of ['--singleLine', '-S']) {
    test(`singleLine=true via ${optionName}`, async (t) => {
      t.plan(1)
      const logLineWithExtra = JSON.stringify(Object.assign(JSON.parse(logLine), {
        extra: {
          foo: 'bar',
          number: 42
        }
      })) + '\n'

      const child = spawn(process.argv[0], [bin, optionName], { env })
      child.on('error', t.assert.fail)
      const endPromise = once(child.stdout, 'data', (data) => {
        t.assert.strictEqual(data.toString(), `[${formattedEpoch}] INFO (42): hello world {"extra":{"foo":"bar","number":42}}\n`)
      })
      child.stdin.write(logLineWithExtra)
      await endPromise
      t.after(() => child.kill())
    })
  }

  test('does ignore nested keys', async (t) => {
    t.plan(1)

    const logLineNested = JSON.stringify(Object.assign(JSON.parse(logLine), {
      extra: {
        foo: 'bar',
        number: 42,
        nested: {
          foo2: 'bar2'
        }
      }
    })) + '\n'

    const child = spawn(process.argv[0], [bin, '-S', '-i', 'extra.foo,extra.nested,extra.nested.miss'], { env })
    child.on('error', t.assert.fail)
    const endPromise = once(child.stdout, 'data', (data) => {
      t.assert.strictEqual(data.toString(), `[${formattedEpoch}] INFO (42 on foo): hello world {"extra":{"number":42}}\n`)
    })
    child.stdin.write(logLineNested)
    await endPromise
    t.after(() => child.kill())
  })

  test('change TZ', async (t) => {
    t.plan(1)
    const child = spawn(process.argv[0], [bin], { env: { ...env, TZ: 'Europe/Amsterdam' } })
    child.on('error', t.assert.fail)
    const endPromise = once(child.stdout, 'data', (data) => {
      t.assert.strictEqual(data.toString(), '[19:35:28.992] INFO (42): hello world\n')
    })
    child.stdin.write(logLine)
    await endPromise
    t.after(() => child.kill())
  })
})
