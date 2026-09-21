// Mastra and AgentFS are timed inside Node; no Python/Node IPC in raw timings.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { createHash } from 'node:crypto';
import readline from 'node:readline';

const config = JSON.parse(await fs.readFile(process.argv[2], 'utf8'));
const require = createRequire(path.join(config.node_prefix, 'package.json'));
const load = name => import(pathToFileURL(require.resolve(name)).href);
const baseline = process.memoryUsage().rss;
const started = performance.now();
await fs.mkdir(config.root, { recursive: true });
let provider, agentfs;
if (config.backend === 'mastra-local') {
  const { LocalFilesystem } = await load('@mastra/core/workspace');
  provider = new LocalFilesystem({ basePath: path.join(config.root, 'files'), contained: true });
  await provider.init();
} else {
  const { AgentFS } = await load('agentfs-sdk');
  agentfs = await AgentFS.open({ path: path.join(config.root, 'files.db') });
  provider = agentfs.fs;
}
const initMs = performance.now() - started;
const isMastra = config.backend === 'mastra-local';

async function write(p, content) {
  if (isMastra) return provider.writeFile(p, content, { recursive: true, overwrite: true });
  // AgentFS writeFile creates parent directories.
  return provider.writeFile('/' + p, content);
}
async function read(p) {
  try {
    const result = isMastra ? await provider.readFile(p, { encoding: 'utf-8' }) : await provider.readFile('/' + p, 'utf8');
    return String(result);
  } catch (e) {
    if (e.code === 'ENOENT' || e.name === 'FileNotFoundError') return null;
    throw e;
  }
}
async function list(dir = '') {
  const entries = isMastra ? await provider.readdir(dir || '.') : await provider.readdirPlus('/' + dir);
  const files = [];
  for (const entry of entries) {
    const p = dir ? dir + '/' + entry.name : entry.name;
    const directory = isMastra ? entry.type === 'directory' : entry.stats.isDirectory();
    if (directory) files.push(...await list(p));
    else files.push(p);
  }
  return files.sort();
}
async function search(query, limit = 10) {
  // These filesystem providers have no substring-search primitive. This is an
  // explicit adapter list/read fallback, not Mastra BM25 or vector search.
  const matches = [];
  for (const p of await list()) {
    if ((await read(p)).includes(query)) matches.push(p);
    if (matches.length >= limit) break;
  }
  return matches;
}
async function remove(p) {
  return isMastra ? provider.deleteFile(p) : provider.unlink('/' + p);
}
async function close() {
  if (agentfs) await agentfs.close();
  else await provider.destroy();
}
if (config.rpc) {
  const input = readline.createInterface({ input: process.stdin });
  for await (const line of input) {
    const request = JSON.parse(line);
    try {
      const operations = { read, write, list, search, delete: remove };
      const result = await operations[request.op](...(request.args || []));
      process.stdout.write(JSON.stringify({ result: result ?? null }) + '\n');
    } catch (e) {
      process.stdout.write(JSON.stringify({ error: e.message }) + '\n');
    }
  }
  await close();
  process.exit(0);
}
if (config.verify_only) {
  await fs.writeFile(config.output, JSON.stringify({ reopen_pass: await read('persist.txt') === 'durable-memory-4829' }));
  await close();
  process.exit(0);
}
const rawCorpus = await fs.readFile(config.corpus);
const corpus = JSON.parse(rawCorpus.toString());
const seedStart = performance.now();
for (const [p, content] of Object.entries(corpus)) await write(p, content);
const seedMs = performance.now() - seedStart;
const seededRss = process.memoryUsage().rss;
const checks = {};
checks.corpus_roundtrip = true;
for (const [p, c] of Object.entries(corpus)) checks.corpus_roundtrip &&= await read(p) === c;
checks.list_complete = JSON.stringify(await list()) === JSON.stringify(Object.keys(corpus).sort());
for (const [key, content] of [['empty', ''], ['unicode', 'café 東京 🌍\r\nsecond\n']]) {
  await write('check.txt', content);
  checks[key] = await read('check.txt') === content;
}
await write('check.txt', 'replacement');
checks.overwrite = await read('check.txt') === 'replacement';
await remove('check.txt');
checks.delete = await read('check.txt') === null;
checks.missing = await read('missing.txt') === null;
for (const query of ['needle-target', 'common-marker', 'not-present-xyz', 'literal%_marker']) {
  const expected = Object.keys(corpus).filter(p => corpus[p].includes(query)).sort().slice(0, 10);
  checks['search_' + query] = JSON.stringify(await search(query)) === JSON.stringify(expected);
}
async function sample(operation) {
  for (let i = 0; i < 3; i++) await operation(i);
  const values = [];
  for (let i = 0; i < config.iterations; i++) {
    const start = performance.now();
    await operation(i);
    values.push(performance.now() - start);
  }
  return values;
}
const first = 'docs/f000000.txt';
const metrics = {};
metrics.read_4k = await sample(() => read(first));
metrics.list = await sample(() => list());
metrics.search_sparse = await sample(() => search('needle-target'));
metrics.search_common_limit10 = await sample(() => search('common-marker'));
metrics.overwrite_same_size = await sample(() => write(first, corpus[first]));
let nextId = 0;
metrics.create_4k = await sample(() => write('new/' + String(nextId++).padStart(6, '0') + '.txt', corpus[first]));
await write('large.txt', 'abcdefghij\n'.repeat(80000));
metrics.read_880k = await sample(() => read('large.txt'));
await write('persist.txt', 'durable-memory-4829');
const storageRss = process.memoryUsage().rss;
const storagePeak = process.resourceUsage().maxRSS * 1024;
let agentInitMs = null;
if (config.agent && isMastra) {
  const start = performance.now();
  const { Agent } = await load('@mastra/core/agent');
  const { createTool } = await load('@mastra/core/tools');
  const { z } = await load('zod');
  let calls = [];
  const readTool = createTool({ id: 'read_file', description: 'Read the full UTF-8 text of a file at path.',
    inputSchema: z.object({ path: z.string() }),
    execute: async ({ path: p }) => { const value = await read(p); calls.push(value); return value; } });
  const model = { specificationVersion: 'v2', provider: 'benchmark', modelId: 'scripted-read', supportedUrls: {},
    async doGenerate(options) {
      const done = options.prompt.some(m => m.role === 'tool');
      return { content: done ? [{ type: 'text', text: 'done' }] : [{ type: 'tool-call', toolCallId: 'read1', toolName: 'read_file', input: JSON.stringify({ path: first }) }],
        finishReason: done ? 'stop' : 'tool-calls', usage: { inputTokens: 0, outputTokens: 0 }, warnings: [] };
    },
    async doStream(options) {
      const result = await this.doGenerate(options);
      return { stream: new ReadableStream({ start(controller) {
        controller.enqueue({ type: 'stream-start', warnings: [] });
        for (const c of result.content) {
          if (c.type === 'text') {
            controller.enqueue({ type: 'text-start', id: 't' });
            controller.enqueue({ type: 'text-delta', id: 't', delta: c.text });
            controller.enqueue({ type: 'text-end', id: 't' });
          } else controller.enqueue(c);
        }
        controller.enqueue({ type: 'finish', finishReason: result.finishReason, usage: result.usage });
        controller.close();
      } }) };
    } };
  const agent = new Agent({ id: 'fs-benchmark', name: 'fs-benchmark', instructions: 'Read the requested file.', model, tools: { read_file: readTool } });
  agentInitMs = performance.now() - start;
  metrics.agent_mock_read = await sample(async () => {
    calls = [];
    const result = await agent.generate('Read docs/f000000.txt.', { maxSteps: 3 });
    if (result.text !== 'done' || calls.length !== 1 || calls[0] !== corpus[first]) throw new Error('Agent did not execute the real read');
  });
}
const versions = {};
for (const name of ['@mastra/core', 'agentfs-sdk']) {
  versions[name] = JSON.parse(await fs.readFile(path.join(config.node_prefix, 'node_modules', name, 'package.json'), 'utf8')).version;
}
const result = { backend: config.backend, files: Object.keys(corpus).length, iterations: config.iterations,
  metrics_ms: metrics, checks, init_ms: initMs, seed_ms: seedMs, rss_baseline_bytes: baseline,
  rss_seeded_bytes: seededRss, rss_storage_bytes: storageRss, peak_storage_rss_bytes: storagePeak,
  rss_after_agent_bytes: process.memoryUsage().rss, agent_init_ms: agentInitMs, versions,
  corpus_sha256: createHash('sha256').update(rawCorpus).digest('hex') };
await close();
await fs.writeFile(config.output, JSON.stringify(result, null, 2));
const medians = Object.fromEntries(Object.entries(metrics).map(([k, v]) => [k, [...v].sort((a, b) => a - b)[Math.floor(v.length / 2)]]));
console.log(JSON.stringify({ backend: config.backend, files: result.files, checks_pass: Object.values(checks).every(Boolean), medians_ms: medians }));
