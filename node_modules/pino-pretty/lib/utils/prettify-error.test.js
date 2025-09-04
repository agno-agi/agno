'use strict'

const { test } = require('node:test')
const stringifySafe = require('fast-safe-stringify')
const prettifyError = require('./prettify-error')

test('prettifies error', t => {
  const error = Error('Bad error!')
  const lines = stringifySafe(error, Object.getOwnPropertyNames(error), 2)

  const prettyError = prettifyError({ keyName: 'errorKey', lines, ident: '    ', eol: '\n' })
  t.assert.match(prettyError, /\s*errorKey: {\n\s*"stack":[\s\S]*"message": "Bad error!"/)
})
