// S-076/4: every command and write brew.js gives an accio agent is on one list, tests/fixtures/brew-curfew.json,
// which test_curfew_brew_contract.py sends through the real curfew hook as that agent. This test renders brew's
// prompts (stub agents, scenarios that reach every step) and checks each command and path in them is on the list,
// and each list entry still appears in a prompt, so a new prompt can't skip curfew's test.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { runWorkflow, happy, story } from './stub.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const CONTRACT = JSON.parse(readFileSync(join(HERE, '..', 'fixtures', 'brew-curfew.json'), 'utf8'))
const SOURCE = readFileSync(join(HERE, '..', '..', 'workflows', 'brew.js'), 'utf8')
const HEAD = '0123456789abcdef0123456789abcdef01234567'
const NO_UI = { ui: false, preview: false, test_data: false }

const pkg = (flags) => async (call, id) => ({ package: `/run/${id}/review-package.md`, head: HEAD, risky: false,
  code: false, breaker: false, ...NO_UI, ...flags })
const findings = (id, who) => ({ verdict: 'fail', counts: { critical: 0, major: 1, minor: 0 },
  path: `.accio/run/${id}/${who}-findings.md` })
const kept = (extra = {}) => async () => ({ skipped: false, repros: [{ file: 'r1.py', verdict: 'kept', reason: 'fails twice',
  claim: 'it resets', source: 'S-001/1', in_dod: true, ...extra }] })
const found = async () => ({ breaks: [{ file: 'r1.py', claim: 'it resets', source: 'S-001/1', verdict: 'kept' }], questions: [] })
const once = (first, then) => { let used = false; return async (...args) => (used ? then(...args) : ((used = true), first(...args))) }

// Each scenario reaches some of brew's steps; together they reach every one.
const SCENARIOS = [
  // A ruling, a review fix round, a boggart fix round, a repair turn; a stacked child.
  () => runWorkflow('brew', happy([story('S-001'), story('S-002', { parents: ['S-001'] })], {
    'S-001 implement': once(async () => ({ status: 'NEEDS_CONTEXT', report: '/run/S-001/build-report.md' }),
      async () => ({ status: 'DONE', head: 'def', report: '/run/S-001/build-report.md' })),
    'S-001 package': pkg({ code: true, breaker: true, risky: true }),
    package: pkg({ code: true, breaker: true }),
    'S-001 examiner': async (call, id) => findings(id, 'examiner'),
    'S-001 boggart': found,
    'S-001 verify': kept(),
    'S-001 verify r2': kept({ cant_load: true }),
    'S-001 verify-repair r2': kept({ verdict: 'fixed' }),
  })),
  // A failed check, mad-eye on a web preview with findings, a boggart skip note.
  () => runWorkflow('brew', happy([story('S-003')], {
    'S-003 check': async () => ({ pass: false, failing: ['python3 -m unittest'], findings: '.accio/run/S-003/check-findings.md' }),
    package: pkg({ ui: true, preview: true, test_data: true }),
    'S-003 mad-eye': async () => ({ findings: [{ id: 'm1', claim: 'the button is hidden' }], checked: ['S-003/1'], skipped: [] }),
  })),
  // mad-eye on a native app's screenshots.
  () => runWorkflow('brew', happy([story('S-004')], {
    package: pkg({ ui: true }),
    'S-004 evidence-plan': async () => ({ ui_evidence: true, takes_over_screen: false, steps_doc: 'docs/ui-walk.md', themes: [] }),
    'S-004 mad-eye-steps': async () => ({ steps: 'open main\n' }),
    'S-004 evidence': async () => ({ ok: true, folder: '.accio/run/S-004/ui-evidence', head: HEAD, screenshots: 1 }),
    'S-004 mad-eye': async () => ({ findings: [], checked: ['S-004/1'], skipped: [] }),
  })),
  // A verify that fails: the story is BLOCKED with a question (S-076/1).
  () => runWorkflow('brew', happy([story('S-005')], {
    package: pkg({ code: true, breaker: true }), 'S-005 boggart': found,
    'S-005 verify': async () => null, 'S-005 verify retry': async () => null,
  })),
]

let rendered
async function allCalls() {
  if (!rendered) rendered = (await Promise.all(SCENARIOS.map((run) => run()))).flatMap((run) => run.calls)
  return rendered
}

const BACKTICKED = /`(accio-[^`]+)`/g
const RUN_PATH = /\.accio\/run\/[A-Za-z0-9_./<>-]*/g
// The list is written with placeholders the Python test fills in: <ID>, <commit> (a head) and <sum> (a steps sum).
const generic = (text) => text.replace(/S-\d{3,}/g, '<ID>').replace(/\b[0-9a-f]{40}\b/g, '<commit>')
  .replace(/--steps-sum [0-9a-f]{8}\b/g, '--steps-sum <sum>')
const commandsIn = (prompt) => [...prompt.matchAll(BACKTICKED)].map((match) => generic(match[1]))
const pathsIn = (prompt) => [...prompt.replace(BACKTICKED, '').matchAll(RUN_PATH)]
  .map((match) => generic(match[0].replace(/\.$/, '')))
const listed = (agent, kind) => ((CONTRACT.brew[agent] || {})[kind] || [])
const step = (call) => call.label.replace(/^S-\d+ /, '').replace(/ retry$/, '').replace(/ r\d+[a-z]?$/, '')

test('S-076/4 every command brew.js gives an agent is on the curfew list for that agent', async () => {
  const missing = new Set()
  for (const call of await allCalls()) {
    const agent = call.opts.agentType
    for (const command of commandsIn(call.prompt)) {
      if (![...listed(agent, 'run'), ...listed(agent, 'mentions')].includes(command)) missing.add(`${agent}: ${command}`)
    }
  }
  assert.deepEqual([...missing], [], 'add these to tests/fixtures/brew-curfew.json (run, or mentions when not run)')
})

test('S-076/4 every .accio/run path brew.js names to an agent is on its list, as a write or a read', async () => {
  const missing = new Set()
  for (const call of await allCalls()) {
    const agent = call.opts.agentType
    for (const path of pathsIn(call.prompt)) {
      if (![...listed(agent, 'write'), ...listed(agent, 'read')].includes(path)) missing.add(`${agent}: ${path}`)
    }
  }
  assert.deepEqual([...missing], [], 'add these to tests/fixtures/brew-curfew.json (write, or read)')
})

test('S-076/4 every entry on the list still appears in a prompt brew.js gives that agent', async () => {
  const seen = new Set()
  for (const call of await allCalls()) {
    for (const item of [...commandsIn(call.prompt), ...pathsIn(call.prompt)]) seen.add(`${call.opts.agentType}: ${item}`)
  }
  const stale = Object.entries(CONTRACT.brew).flatMap(([agent, lists]) =>
    Object.values(lists).flat().map((item) => `${agent}: ${item}`)).filter((entry) => !seen.has(entry))
  assert.deepEqual(stale, [], 'these are on the list but no prompt gives them any more')
})

test('S-076/4 the scenarios reach every step and agent brew.js has, so no prompt goes unchecked', async () => {
  const calls = await allCalls()
  const steps = new Set(calls.map(step))
  const agents = new Set(calls.map((call) => call.opts.agentType))
  const literal = (pattern) => [...SOURCE.matchAll(pattern)].map((match) => match[1])
  const wanted = [
    ...literal(/label\(story, '([a-z-]+)'/g), ...literal(/verify\(story, '([a-z-]+)'/g),
    ...literal(/previewStep\(story, '([a-z]+)'/g).map((action) => `preview-${action}`),
    ...literal(/label: '([a-z]+)'/g), ...literal(/ROLES = \{([^}]*)\}/g)[0].match(/[a-z]+(?=:)/g),
  ]
  assert.ok(wanted.length > 20, `found only ${wanted.length} steps in brew.js`)
  assert.deepEqual(wanted.filter((name) => !steps.has(name)), [], 'add a scenario that reaches these steps')
  const constants = Object.fromEntries(literal(/const ([A-Z_]+) = '(accio:[a-z-]+)'/g).map((name) =>
    [name, SOURCE.match(new RegExp(`const ${name} = '(accio:[a-z-]+)'`))[1]]))
  const types = literal(/agentType: ([A-Z_]+)/g).map((name) => constants[name])
  assert.ok(types.length && types.every(Boolean), 'every agentType names a constant')
  assert.deepEqual([...new Set(types)].filter((type) => !agents.has(type)), [])
  assert.ok(Object.keys(CONTRACT.brew).every((agent) => agents.has(agent)))
})
