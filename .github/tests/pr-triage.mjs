import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

// Execute the real github-script body, including the final label/comment/close
// decisions. Every GitHub boundary is mocked; these tests never contact GitHub.
const path = process.argv[2] || new URL('../workflows/pr-triage.yml', import.meta.url);
const workflow = readFileSync(path, 'utf8');
const script = workflow.split('          script: |\n')[1];
assert.ok(script, 'PR Triage script must exist');
const source = script.split('\n').map(line => line.replace(/^ {12}/, '')).join('\n');
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const run = new AsyncFunction('github', 'context', 'console', source);

const candidate = (body, number = 9045) => ({ number, body, pull_request: {} });

async function triage(items, body = 'Closes #10659. Resolve Claude document attachment MIME types from the file.') {
  const calls = { labels: [], comments: [], closes: [], searches: [] };
  async function search(args) {
    if (args.q.includes('author:')) return { data: { total_count: 2, items: [] } };
    calls.searches.push(args);
    return { data: { total_count: items.length, items: items.slice(0, args.per_page) } };
  }
  const github = {
    rest: {
      repos: { getCollaboratorPermissionLevel: async () => ({ data: { permission: 'read' } }) },
      search: { issuesAndPullRequests: search },
      pulls: {
        listFiles: async () => {},
        get: async ({ pull_number }) => ({ data: items.find(item => item.number === pull_number) }),
        update: async args => { calls.closes.push(args); },
      },
      issues: {
        get: async () => ({ data: { assignees: [] } }),
        addLabels: async args => { calls.labels.push(...args.labels); },
        createComment: async args => { calls.comments.push(args.body); },
      },
    },
    paginate: async (method, args) => {
      if (method === github.rest.pulls.listFiles) return [];
      assert.equal(method, github.rest.search.issuesAndPullRequests);
      calls.searches.push(args);
      return items;
    },
  };
  const context = {
    repo: { owner: 'agno-agi', repo: 'agno' },
    payload: { pull_request: { number: 10660, user: { login: 'reporter' }, author_association: 'NONE', body } },
  };
  await run(github, context, { log() {} });
  return calls;
}

function assertDuplicate(calls, expected) {
  assert.equal(calls.labels.includes('possible-duplicate'), expected);
  assert.equal(calls.comments.some(body => body.includes('**Possible duplicate:**')), expected);
  assert.equal(calls.closes.length, expected ? 1 : 0);
  if (expected) assert.equal(calls.closes[0].state, 'closed');
}

for (const [name, body, expected] of [
  ['plain test count', '10659 passed', false],
  ['different closing reference', 'Closes #9044', false],
  ['larger issue number', 'Fixes #106590', false],
  ['different repository URL', 'https://github.com/other/project/issues/10659', false],
  ['missing body', null, false],
  ['empty body', '', false],
  ['closing keyword', 'Closes #10659', true],
  ['case-insensitive keyword', 'FIXES #10659', true],
  ['exact repository URL', 'https://github.com/agno-agi/agno/issues/10659', true],
  ['multiple closing references', 'Closes #9044\nResolves #10659', true],
]) {
  test(name, async () => assertDuplicate(await triage([candidate(body)]), expected));
}

test('ignore the PR itself and results that are not pull requests', async () => {
  assertDuplicate(await triage([candidate('Closes #10659', 10660), { number: 10700, body: 'Closes #10659' }]), false);
});

test('global regex state is reset between candidate bodies', async () => {
  const calls = await triage([candidate('Fixes #10659', 9045), candidate('Fixes #10659', 9046)]);
  assertDuplicate(calls, true);
  assert.ok(calls.comments[0].includes('#9045'));
  assert.ok(calls.comments[0].includes('#9046'));
});

test('find a real reference after ten unrelated numeric hits', async () => {
  const items = Array.from({ length: 10 }, (_, index) => candidate('10659 passed', 9000 + index));
  items.push(candidate('Closes #10659'));
  assertDuplicate(await triage(items), true);
});

test('paginate when a real reference is beyond the first hundred search hits', async () => {
  const items = Array.from({ length: 100 }, (_, index) => candidate('10659 passed', 9000 + index));
  items.push(candidate('Closes #10659', 9200));
  assertDuplicate(await triage(items), true);
});

test('parse the incoming issue URL using the same reference rules', async () => {
  assertDuplicate(await triage([candidate('Resolves #10659')],
    'Fix incorrect attachment MIME type; https://github.com/agno-agi/agno/issues/10659'), true);
});
