'use strict'

const getEsmExports = require('./get-esm-exports.js')
const { parse: parseCjs } = require('cjs-module-lexer')
const { readFileSync } = require('fs')
const { builtinModules } = require('module')
const { fileURLToPath, pathToFileURL } = require('url')
const { dirname } = require('path')

function addDefault (arr) {
  return new Set(['default', ...arr])
}

// Cached exports for Node built-in modules
const BUILT_INS = new Map()

function getExportsForNodeBuiltIn (name) {
  let exports = BUILT_INS.get()

  if (!exports) {
    exports = new Set(addDefault(Object.keys(require(name))))
    BUILT_INS.set(name, exports)
  }

  return exports
}

const urlsBeingProcessed = new Set() // Guard against circular imports.

async function getCjsExports (url, context, parentLoad, source) {
  if (urlsBeingProcessed.has(url)) {
    return []
  }
  urlsBeingProcessed.add(url)

  try {
    const result = parseCjs(source)
    const full = addDefault(result.exports)

    await Promise.all(result.reexports.map(async re => {
      if (re.startsWith('node:') || builtinModules.includes(re)) {
        for (const each of getExportsForNodeBuiltIn(re)) {
          full.add(each)
        }
      } else {
        if (re === '.') {
          re = './'
        }
        // Resolve the re-exported module relative to the current module.
        const newUrl = pathToFileURL(require.resolve(re, { paths: [dirname(fileURLToPath(url))] })).href

        if (newUrl.endsWith('.node') || newUrl.endsWith('.json')) {
          return
        }

        for (const each of await getExports(newUrl, context, parentLoad)) {
          full.add(each)
        }
      }
    }))

    return full
  } finally {
    urlsBeingProcessed.delete(url)
  }
}

/**
 * Inspects a module for its type (commonjs or module), attempts to get the
 * source code for said module from the loader API, and parses the result
 * for the entities exported from that module.
 *
 * @param {string} url A file URL string pointing to the module that
 * we should get the exports of.
 * @param {object} context Context object as provided by the `load`
 * hook from the loaders API.
 * @param {Function} parentLoad Next hook function in the loaders API
 * hook chain.
 *
 * @returns {Promise<Set<string>>} An array of identifiers exported by the module.
 * Please see {@link getEsmExports} for caveats on special identifiers that may
 * be included in the result set.
 */
async function getExports (url, context, parentLoad) {
  // `parentLoad` gives us the possibility of getting the source
  // from an upstream loader. This doesn't always work though,
  // so later on we fall back to reading it from disk.
  const parentCtx = await parentLoad(url, context)
  let source = parentCtx.source
  const format = parentCtx.format

  if (!source) {
    if (format === 'builtin') {
      // Builtins don't give us the source property, so we're stuck
      // just requiring it to get the exports.
      return getExportsForNodeBuiltIn(url)
    }

    // Sometimes source is retrieved by parentLoad, CommonJs isn't.
    source = readFileSync(fileURLToPath(url), 'utf8')
  }

  try {
    if (format === 'module') {
      return getEsmExports(source)
    }

    if (format === 'commonjs') {
      return await getCjsExports(url, context, parentLoad, source)
    }

    // At this point our `format` is either undefined or not known by us. Fall
    // back to parsing as ESM/CJS.
    const esmExports = getEsmExports(source)
    if (!esmExports.length) {
      // TODO(bengl) it's might be possible to get here if somehow the format
      // isn't set at first and yet we have an ESM module with no exports.
      // I couldn't construct an example that would do this, so maybe it's
      // impossible?
      return await getCjsExports(url, context, parentLoad, source)
    }
  } catch (cause) {
    const err = new Error(`Failed to parse '${url}'`)
    err.cause = cause
    throw err
  }
}

module.exports = getExports
