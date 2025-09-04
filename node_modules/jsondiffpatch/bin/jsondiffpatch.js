#!/usr/bin/env node

import { readFileSync } from 'node:fs';
import * as jsondiffpatch from '../lib/with-text-diffs.js';
import * as consoleFormatter from '../lib/formatters/console.js';

const fileLeft = process.argv[2];
const fileRight = process.argv[3];

if (!fileLeft || !fileRight) {
  console.log('\n  USAGE: jsondiffpatch left.json right.json');
} else {
  const left = JSON.parse(readFileSync(fileLeft));
  const right = JSON.parse(readFileSync(fileRight));

  const delta = jsondiffpatch.diff(left, right);
  consoleFormatter.log(delta);
}
