// S-068: mad-eye on a native app. With `ui_evidence` in config, mad-eye writes a steps file, prefect runs
// `accio-preview <ID> evidence` on it, and mad-eye judges the screenshots with Read only. Driven by stub.mjs.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { runWorkflow, happy, story, fail, pass } from './stub.mjs'

const AGENTS = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'agents')
const labels = (calls) => calls.map((call) => call.label)
const steps = (calls, id) => labels(calls).filter((label) => label.startsWith(`${id} `)).map((label) => label.slice(id.length + 1))
const prompt = (calls, label) => calls.find((call) => call.label === label).prompt
const callOf = (calls, label) => calls.find((call) => call.label === label)
const flat = (text) => text.replace(/\s+/g, ' ')

const HEAD = 'a'.repeat(40)
const OTHER = 'b'.repeat(40)
const native = (extra = {}) => async (call, id) => ({
  package: `/run/${id}/review-package.md`, head: HEAD, risky: false, code: false, breaker: false,
  ui: true, preview: false, test_data: false, ...extra,
})
const PLAN = { ui_evidence: true, takes_over_screen: false, steps_doc: 'docs/ui-walk.md', themes: ['light', 'dark'] }
const STEPS = { steps: 'open main\nresize 800x600\nminimize\nrestore\nswitch-tab 2\n' }
const RAN = { ok: true, folder: '/r/.accio/run/S-001/ui-evidence', head: HEAD, screenshots: 4 }
const SEEN = { findings: [{ id: 'mad-eye-1', where: 'terminal pane', claim: 'shows a live terminal', dod: 'S-001/2', failure: 'the pane is blank after restore', screenshot: '/r/.accio/run/S-001/ui-evidence/dark/restore.png' }] }
const EVIDENCE_WALK = ['evidence-plan', 'mad-eye-steps', 'evidence', 'mad-eye']

const overrides = (extra = {}) => ({
  package: native(), 'evidence-plan': async () => PLAN, 'mad-eye-steps': async () => STEPS, evidence: async () => RAN, ...extra,
})
const run = (extra) => runWorkflow('brew', happy([story('S-001')], overrides(extra)))
const skipNote = (result) => (result.match(/mad-eye skipped: ([^;\n]*)/) || [])[1] || ''

test('S-068/1 with ui_evidence, mad-eye writes steps, prefect runs them in the worktree, then mad-eye judges the folder', async () => {
  const { result, calls } = await run()
  assert.deepEqual(steps(calls, 'S-001').slice(-5), EVIDENCE_WALK.concat('outcome'))
  assert.ok(!labels(calls).some((label) => /preview-(start|stop)/.test(label)), 'no web preview is started')
  assert.equal(callOf(calls, 'S-001 evidence-plan').opts.agentType, 'accio:prefect')
  assert.match(prompt(calls, 'S-001 evidence-plan'), /accio-preview S-001 evidence-plan/)
  assert.equal(callOf(calls, 'S-001 mad-eye-steps').opts.agentType, 'accio:mad-eye')
  const asked = flat(prompt(calls, 'S-001 mad-eye-steps'))
  assert.match(asked, /\/run\/S-001\/review-package\.md/)
  assert.match(asked, /\/wt\/S-001\/docs\/ui-walk\.md/)
  assert.match(asked, /resize, minimize and restore, and tab switching/)
  assert.match(asked, /\{"steps":/)
  const ran = callOf(calls, 'S-001 evidence')
  assert.equal(ran.opts.agentType, 'accio:prefect')
  assert.match(ran.prompt, new RegExp(`accio-preview S-001 evidence --head ${HEAD}`))
  assert.match(ran.prompt, /\.accio\/run\/S-001\/ui-steps\.txt/)
  assert.ok(ran.prompt.includes(JSON.stringify(STEPS.steps)), 'the steps text goes to prefect unchanged')
  assert.ok(ran.prompt.indexOf('ui-steps.txt') < ran.prompt.indexOf('accio-preview S-001 evidence --head'), 'written before the run')
  assert.match(prompt(calls, 'S-001 mad-eye'), /\.accio\/run\/S-001\/ui-evidence\//)
  assert.match(result, /S-001 Story S-001\s+READY/)
})

test('S-068/1 the evidence path is not taken for a web preview, and a config with neither says so', async () => {
  const web = await run({ package: native({ preview: true, test_data: true }) })
  assert.ok(!labels(web.calls).includes('S-001 evidence-plan'))
  assert.ok(labels(web.calls).includes('S-001 preview-start'))
  const none = await run({ 'evidence-plan': async () => ({ ui_evidence: false }) })
  assert.deepEqual(steps(none.calls, 'S-001').slice(-3), ['professor', 'evidence-plan', 'outcome'])
  assert.equal(skipNote(none.result), 'config.json has no `preview` or `ui_evidence`')
})

test('S-068/1 a plan reply without ui_evidence is retried, and a plan that fails is a skip, not a block', async () => {
  const { calls } = await run({ 'evidence-plan': async (call) => (call.label.endsWith('retry') ? PLAN : { takes_over_screen: false }) })
  assert.ok(labels(calls).includes('S-001 evidence-plan retry'))
  const broken = await run({ 'evidence-plan': async () => ({ ui_evidence: false, error: 'bad config' }) })
  assert.match(broken.result, /READY/)
  assert.match(skipNote(broken.result), /bad config/)
})

test('S-068/2 a failing, timed-out or screenshot-less command skips mad-eye with its reason, and the story is READY', async () => {
  const reasons = ['the evidence command exited with 3 (see /r/.accio/run/S-001/ui-evidence.log)',
    'the evidence command ran past its timeout of 600s and was stopped (see /r/.accio/run/S-001/ui-evidence.log)',
    'the evidence command left no PNG screenshots in /r/.accio/run/S-001/ui-evidence']
  for (const reason of reasons) {
    const { result, calls } = await run({ evidence: async () => ({ skipped: true, reason }) })
    assert.ok(!labels(calls).includes('S-001 mad-eye'), reason)
    assert.match(result, /S-001 Story S-001\s+READY/, reason)
    assert.equal(skipNote(result), reason)
  }
})

test('S-068/2 an evidence step that errors or gives no answer is a skip, not a block', async () => {
  for (const reply of [async () => ({ error: 'it broke' }), async () => null]) {
    const { result, calls } = await run({ evidence: reply })
    assert.ok(!labels(calls).includes('S-001 mad-eye'))
    assert.match(result, /READY/)
    assert.match(skipNote(result), /the evidence command did not run/)
  }
})

test('S-068/2 mad-eye writing no steps is a skip, and nothing runs', async () => {
  for (const reply of [async () => ({ steps: '  ' }), async () => null, async () => ({ error: 'no tools' })]) {
    const { result, calls } = await run({ 'mad-eye-steps': reply })
    assert.ok(!labels(calls).includes('S-001 evidence'))
    assert.match(result, /READY/)
    assert.match(skipNote(result), /mad-eye wrote no steps/)
  }
})

test('S-068/3 the judging prompt asks for screenshots in every theme, element dumps when present, one screenshot per line, Read only', async () => {
  const { calls } = await run()
  const judged = flat(prompt(calls, 'S-001 mad-eye'))
  assert.match(judged, /only Read/)
  assert.match(judged, /no browser tools/)
  assert.match(judged, /screenshots/)
  assert.match(judged, /light, dark/)
  assert.match(judged, /element dumps/)
  assert.match(judged, /one screenshot per line/)
  assert.match(flat(prompt(calls, 'S-001 mad-eye-steps')), /only Read/)
  const plain = await run({ 'evidence-plan': async () => ({ ...PLAN, themes: [] }) })
  assert.match(flat(prompt(plain.calls, 'S-001 mad-eye')), /the app's default look/)
})

test('S-068/3 mad-eye.md has an evidence mode that uses only Read and judges from the screenshots', () => {
  const text = flat(readFileSync(join(AGENTS, 'mad-eye.md'), 'utf8'))
  const mode = text.split('**Evidence mode')[1]
  assert.ok(mode, 'mad-eye.md has an evidence mode section')
  assert.match(mode, /only Read/)
  assert.match(mode, /\{"steps": "<the file's text>"\}/)
  assert.match(mode, /every theme/)
  assert.match(mode, /one screenshot per line/)
  assert.match(mode, /element dumps/)
  assert.match(mode, /resize, minimize and restore, and tab switching/)
  assert.match(mode, /blank, garbled/)
})

test('S-068/4 a missing, blank, garbled or wrong screen becomes mad-eye-findings.md and goes to a fix round', async () => {
  const { result, calls } = await run({ 'mad-eye': async () => SEEN })
  assert.deepEqual(steps(calls, 'S-001').slice(6), EVIDENCE_WALK.concat(['mad-eye-findings r1', 'fix-brief r1', 'fix r1', 'check r1',
    'package r1c', 'examiner r1', 'professor r1', 'outcome']))
  assert.match(prompt(calls, 'S-001 mad-eye-findings r1'), /\.accio\/run\/S-001\/mad-eye-findings\.md[\s\S]*blank after restore/)
  assert.match(prompt(calls, 'S-001 fix-brief r1'), /accio-brief S-001 --fix \.accio\/run\/S-001\/mad-eye-findings\.md/)
  assert.match(result, /S-001 Story S-001\s+READY/)
})

test('S-068/4 findings in the screenshots after two fix rounds block the story with a question', async () => {
  const { result, calls } = await run({
    'mad-eye': async () => SEEN,
    examiner: async (call, id) => (call.label.endsWith(' r2') ? pass(id, 'examiner') : fail(id, 'examiner')),
  })
  assert.match(prompt(calls, 'S-001 outcome'), /BLOCKED[\s\S]*screenshots[\s\S]*blank after restore/)
  assert.match(result, /S-001 Story S-001\s+BLOCKED/)
})

test('S-068/4 after a fix round mad-eye reads the whole story, and the evidence is of the new head', async () => {
  const heads = { package: HEAD, 'package r1': OTHER }
  const { calls } = await run({
    package: async (call, id) => ({ ...(await native()(call, id)), head: heads[call.label.slice(6)] || OTHER }),
    'S-001 professor': async (call, id) => fail(id, 'professor'),
    evidence: async () => ({ ...RAN, head: OTHER }),
  })
  assert.ok(labels(calls).includes('S-001 package r1m'))
  assert.match(prompt(calls, 'S-001 evidence'), new RegExp(`--head ${OTHER}`))
  assert.ok(labels(calls).includes('S-001 mad-eye'))
})

test('S-068/5 evidence whose stamp names another commit is refused: mad-eye is skipped with both commits named', async () => {
  const { result, calls } = await run({ evidence: async () => ({ ...RAN, head: OTHER }) })
  assert.ok(!labels(calls).includes('S-001 mad-eye'))
  assert.match(result, /READY/)
  assert.ok(skipNote(result).includes(OTHER) && skipNote(result).includes(HEAD), skipNote(result))
  const missing = await run({ evidence: async () => ({ ok: true, folder: RAN.folder, screenshots: 1 }) })
  assert.ok(!labels(missing.calls).includes('S-001 mad-eye'))
  assert.match(skipNote(missing.result), new RegExp(`commit none but the story's head is ${HEAD}`))
  const told = 'the evidence is of commit bbbbbbbbbbbb but the story\'s head is aaaaaaaaaaaa, so it is refused'
  const refused = await run({ evidence: async () => ({ skipped: true, reason: told }) })
  assert.equal(skipNote(refused.result), told)
})

// S-070: ask accio's own Python (preview.steps_sum, policy.PREFECT_PREVIEW) about what brew.js wrote.
const BIN = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'bin')
const python = (code, ...args) => execFileSync('python3', ['-c', `import sys; sys.path.insert(0, ${JSON.stringify(BIN)}); ${code}`, ...args], { encoding: 'utf8' }).trim()
const pythonSum = (text) => python('from accio_lib import preview; print(preview.steps_sum(sys.argv[1]))', text)
const previewCommands = (calls) => calls.flatMap((call) => [...call.prompt.matchAll(/`accio-preview ([^`]*)`/g)].map((match) => match[1]))
const prefectMayRun = (args) => python('from accio_lib import policy; print(bool(policy.PREFECT_PREVIEW.fullmatch(sys.argv[1])))', args) === 'True'

test('S-070/4 brew passes the checksum of the steps mad-eye sent, computed as accio-preview computes it', async () => {
  for (const text of [STEPS.steps, 'open main\n', 'café ☕ \u{1F600}\r\nswitch-tab 2']) {
    const { calls } = await run({ 'mad-eye-steps': async () => ({ steps: text }) })
    const sum = (prompt(calls, 'S-001 evidence').match(/--steps-sum ([0-9a-f]+)/) || [])[1]
    assert.equal(sum, pythonSum(text), JSON.stringify(text))
  }
})

test('S-070/4 a changed ui-steps.txt never runs: mad-eye is skipped with a note saying the steps file was changed', async () => {
  const reason = 'the steps file ui-steps.txt was changed: its checksum is 00000000, not the 1234abcd of the steps mad-eye wrote, so the evidence command did not run'
  const { result, calls } = await run({ evidence: async () => ({ skipped: true, reason }) })
  assert.ok(!labels(calls).includes('S-001 mad-eye'))
  assert.match(result, /S-001 Story S-001\s+READY/)
  assert.match(skipNote(result), /the steps file ui-steps\.txt was changed/)
})

test('S-070/1 every accio-preview command brew gives prefect is one curfew lets prefect run', async () => {
  const app = await run()
  const web = await run({ package: native({ preview: true, test_data: true }) })
  const commands = [...previewCommands(app.calls), ...previewCommands(web.calls)]
  for (const action of ['start', 'stop', 'evidence-plan', 'evidence --head']) {
    assert.ok(commands.some((args) => args.startsWith(`S-001 ${action}`)), `brew gives prefect ${action}`)
  }
  for (const args of commands) assert.ok(prefectMayRun(args), args)
})

test('S-068/7 a command that takes over the screen never runs: mad-eye is skipped with a note saying why', async () => {
  const { result, calls } = await run({ 'evidence-plan': async () => ({ ...PLAN, takes_over_screen: true }) })
  assert.deepEqual(steps(calls, 'S-001').slice(-3), ['professor', 'evidence-plan', 'outcome'])
  assert.match(result, /READY/)
  assert.match(skipNote(result), /takes over the screen.*can't run in an unattended build/)
})
