import fs from "node:fs";
import assert from "node:assert/strict";
const workflow = fs.readFileSync(
  new URL("../workflows/pr-triage.yml", import.meta.url),
  "utf8",
);
const source = workflow
  .split("          script: |\n")[1]
  .replace(/^ {12}/gm, "");
const oracle = { body: "Unit tests: 10659 passed. Closes #9044" };
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const execute = new AsyncFunction("github", "context", source);
let failures = 0;
for (const [name, body, expected] of [
  ["actual unrelated Oracle test count", oracle.body, false],
  ["bare test count", "Unit suite: 10659 passed", false],
  ["different issue number", "Closes #106590", false],
  ["genuine closing reference", "Fixes #10659", true],
  ["missing body", null, false],
  ["genuine issue URL", "https://github.com/agno-agi/agno/issues/10659", true],
]) {
  const writes = [];
  const github = {
    paginate: async () => [],
    rest: {
      repos: {
        getCollaboratorPermissionLevel: async () => ({
          data: { permission: "read" },
        }),
      },
      search: {
        issuesAndPullRequests: async ({ q }) => ({
          data: q.includes("author:")
            ? { total_count: 2, items: [] }
            : {
                items: [
                  {
                    number: 9045,
                    pull_request: { url: "https://example.invalid/pr/9045" },
                    body,
                  },
                ],
              },
        }),
      },
      issues: {
        get: async () => ({ data: { assignees: [] } }),
        addLabels: async (data) => writes.push({ type: "labels", ...data }),
        createComment: async (data) =>
          writes.push({ type: "comment", ...data }),
      },
      pulls: {
        update: async (data) => writes.push({ type: "update", ...data }),
      },
    },
  };
  await execute(github, {
    repo: { owner: "agno-agi", repo: "agno" },
    payload: {
      pull_request: {
        number: 10660,
        user: { login: "contributor" },
        author_association: "NONE",
        body: "Fixes #10659\nHandle document MIME types consistently for text attachments.",
      },
    },
  });
  const closed = writes.some(
    (w) => w.type === "update" && w.state === "closed",
  );
  const passed = closed === expected;
  failures += !passed;
  assert.equal(
    writes.some(
      (w) => w.type === "labels" && w.labels.includes("possible-duplicate"),
    ),
    expected,
  );
  assert.equal(
    writes.some(
      (w) => w.type === "comment" && w.body.includes("Possible duplicate"),
    ),
    expected,
  );
  console.log(
    JSON.stringify({
      case: name,
      expected_closed: expected,
      actual_closed: closed,
      passed,
    }),
  );
}
console.log(
  JSON.stringify({
    failures,
    total: 6,
    scope:
      "complete extracted workflow script; all API calls mocked; no external writes",
  }),
);
process.exitCode = failures ? 1 : 0;
