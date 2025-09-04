'use strict'

const { test } = require('node:test')
const joinLinesWithIndentation = require('./join-lines-with-indentation')

test('joinLinesWithIndentation adds indentation to beginning of subsequent lines', t => {
  const input = 'foo\nbar\nbaz'
  const result = joinLinesWithIndentation({ input })
  t.assert.strictEqual(result, 'foo\n    bar\n    baz')
})

test('joinLinesWithIndentation accepts custom indentation, line breaks, and eol', t => {
  const input = 'foo\nbar\r\nbaz'
  const result = joinLinesWithIndentation({ input, ident: '  ', eol: '^' })
  t.assert.strictEqual(result, 'foo^  bar^  baz')
})
