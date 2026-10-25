// S-080: a reviewer (or boggart) that can't read its inputs replies `incomplete`; brew stops the story instead of
// counting a pass, driven by stub.mjs.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { runWorkflow, happy, story, fail, pass } from './stub.mjs'

const NO_UI = { ui: false, preview: false, test_data: false }
const labels = (calls) => calls.map((call) => call.label)
const steps = (calls, id) => labels(calls).filter((label) => label.startsWith(`${id} `)).map((label) => label.slice(id.length + 1))
const prompt = (calls, label) => calls.find((call) => call.label === label).prompt
const ZERO = { critical: 0, major: 0, minor: 0 }
const incomplete = (missing) => async (call, id) => ({ verdict: 'incomplete', counts: ZERO, path: `/run/${id}/x-findings.md`, missing })
const risky = async (call, id) => ({ package: `/run/${id}/review-package.md`, head: 'h0', risky: true, code: false, breaker: false, ...NO_UI })
const withCode = async (call, id) => ({ package: `/run/${id}/review-package.md`, head: 'h0', risky: false, code: true, breaker: true, ...NO_UI })

test('S-080/1 the review schema takes an incomplete verdict with a missing string', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')]))
  const schema = calls.find((call) => call.label === 'S-001 examiner').opts.schema
  assert.deepEqual(schema.properties.verdict.enum, ['pass', 'fail', 'incomplete'])
  assert.equal(schema.properties.missing.type, 'string')
  assert.match(prompt(calls, 'S-001 examiner'), /missing when the verdict is incomplete/)
})

test('S-080/1 an incomplete examiner, professor or auror blocks the story with one question naming it and the file', async () => {
  const cases = [['examiner', 'spec reviewer'], ['professor', 'code reviewer'], ['auror', 'security reviewer']]
  for (const [name, role] of cases) {
    const missing = `.accio/run/S-001/${name}-needs.md`
    const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
      package: risky, [name]: incomplete(missing),  // the first try and the retry
    }))
    assert.ok(!steps(calls, 'S-001').some((step) => step.startsWith('fix')), name)  // no fix round
    assert.deepEqual(steps(calls, 'S-001').slice(-1), ['outcome'], name)
    assert.match(result, /S-001 Story S-001\s+BLOCKED\s+1 question for you/, name)
    const outcome = prompt(calls, 'S-001 outcome')
    assert.ok(outcome.includes(`The ${role} (${name}) couldn't read ${missing}, so it gave no verdict. Fix that and review again?`), name)
    assert.match(outcome, /first line of the question file exactly `accio`/, name)
  }
})

test('S-080/1 an incomplete reply wins over a fail from another reviewer: still no fix round', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    'S-001 examiner': async (call, id) => fail(id, 'examiner'),
    professor: incomplete('the diff'),
  }))
  assert.ok(!steps(calls, 'S-001').some((step) => step.startsWith('fix')))
  assert.match(result, /BLOCKED/)
  assert.match(prompt(calls, 'S-001 outcome'), /code reviewer \(professor\) couldn't read the diff/)
})

test('S-080/1 an incomplete reviewer in a fix round blocks the story too', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    'S-001 examiner': async (call, id) => fail(id, 'examiner'),
    'S-001 examiner r1': incomplete('/run/S-001/review-package.md'),
    'S-001 examiner again r1': incomplete('/run/S-001/review-package.md'),
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(-3), ['examiner r1', 'examiner again r1', 'outcome'])
  assert.match(result, /BLOCKED/)
  assert.match(prompt(calls, 'S-001 outcome'), /spec reviewer \(examiner\) couldn't read \/run\/S-001\/review-package\.md/)
})

test('S-080/1 an incomplete reply with no missing says it could not read its inputs', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')], {
    examiner: async (call, id) => ({ verdict: 'incomplete', counts: ZERO, path: `/run/${id}/e.md` }),
  }))
  assert.match(prompt(calls, 'S-001 outcome'), /spec reviewer \(examiner\) couldn't read its inputs, so it gave no verdict/)
})

test('an incomplete reviewer gets one more try, and a pass on it lets the story go on', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    'S-001 examiner': incomplete('/run/S-001/review.diff'),
  }))
  assert.deepEqual(steps(calls, 'S-001'), ['prepare', 'implement', 'check', 'package', 'examiner', 'professor',
    'examiner again', 'outcome'])
  assert.match(prompt(calls, 'S-001 examiner again'), /last try couldn't read \/run\/S-001\/review\.diff: read it again/)
  assert.match(result, /S-001 Story S-001\s+READY/)
})

test('a fail on the retry goes to a fix round like any fail; only the incomplete reviewer is asked again', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')], {
    'S-001 professor': incomplete('a checklist'),
    'S-001 professor again': async (call, id) => fail(id, 'professor'),
  }))
  const seen = steps(calls, 'S-001')
  assert.ok(!seen.includes('examiner again'))
  assert.deepEqual(seen.slice(4, 9), ['examiner', 'professor', 'professor again', 'fix-brief r1', 'fix r1'])
})

test('S-080/2 reviewers that pass or fail review and fix as before', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    'S-001 professor': async (call, id) => fail(id, 'professor'),
    'S-001 professor r1': async (call, id) => pass(id, 'professor'),
  }))
  assert.deepEqual(steps(calls, 'S-001'), ['prepare', 'implement', 'check', 'package', 'examiner', 'professor',
    'fix-brief r1', 'fix r1', 'check r1', 'package r1', 'professor r1', 'outcome'])
  assert.match(result, /S-001 Story S-001\s+READY/)
  assert.doesNotMatch(prompt(calls, 'S-001 outcome'), /couldn't read/)
})

test('S-080/3 a boggart that replies incomplete keeps the story going with a note naming what it could not read', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    package: withCode, boggart: async () => ({ breaks: [], questions: [], incomplete: true, missing: 'src/app.py' }),
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(-2), ['boggart', 'outcome'])
  assert.match(result, /S-001 Story S-001\s+READY\s+boggart couldn't read src\/app\.py/)
  assert.ok(prompt(calls, 'S-001 outcome').includes(JSON.stringify("boggart couldn't read src/app.py")))
})

test('S-080/3 a boggart that is incomplete but found breaks still has them verified', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    package: withCode,
    boggart: async () => ({ breaks: [{ file: 'r1.py', claim: 'c', source: 'S-001/1', verdict: 'kept' }], incomplete: true, missing: 'b.py' }),
    verify: async () => ({ skipped: false, repros: [{ file: 'r1.py', verdict: 'dropped', reason: 'passed on head' }] }),
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(-3), ['boggart', 'verify', 'outcome'])
  assert.match(result, /READY\s+boggart couldn't read b\.py/)
})

test('S-080/3 the boggart reply schema carries incomplete and missing', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')], { package: withCode, boggart: async () => ({ breaks: [] }) }))
  const props = calls.find((call) => call.label === 'S-001 boggart').opts.schema.properties
  assert.equal(props.incomplete.type, 'boolean')
  assert.equal(props.missing.type, 'string')
  assert.match(prompt(calls, 'S-001 boggart'), /incomplete and missing when you couldn't read a file/)
})
