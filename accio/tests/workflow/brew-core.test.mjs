// S-019: brew.js load, prepare, implement, check, outcome (DESIGN § 3.4, § 12.6), driven by stub.mjs's fake agent().
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { runWorkflow, happy, story, sleep, fail } from './stub.mjs'

const AGENTS = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'agents')
const labels = (calls) => calls.map((call) => call.label)
const steps = (calls, id) => labels(calls).filter((label) => label.startsWith(`${id} `)).map((label) => label.split(' ')[1])

test('S-019/1 at most 3 stories are in progress at once', async () => {
  let inProgress = 0
  let most = 0
  const stories = ['S-001', 'S-002', 'S-003', 'S-004', 'S-005'].map((id) => story(id))
  const { result } = await runWorkflow('brew', happy(stories, {
    prepare: async (call, id) => { inProgress += 1; most = Math.max(most, inProgress); return { worktree: 'w', brief: 'b', base: 'a' } },
    implement: async () => { await sleep(20); return { status: 'DONE' } },
    outcome: async () => { inProgress -= 1; return { done: true } },
  }))
  assert.equal(most, 3)
  assert.match(result, /Build finished: 5 stories/)
  assert.equal((result.match(/READY/g) || []).length, 5)
})

test('S-019/2 a silent or failing agent leaves its story BLOCKED with a plain question', async () => {
  const stories = [story('S-001'), story('S-002')]
  const { result, calls } = await runWorkflow('brew', happy(stories, {
    'S-001 implement': async () => null,
    'S-002 implement': async () => { throw new Error('stalled') },
  }))
  assert.match(result, /S-001 Story S-001\s+BLOCKED/)
  assert.match(result, /S-002 Story S-002\s+BLOCKED/)
  const question = calls.find((call) => call.label === 'S-001 outcome').prompt
  assert.match(question, /stopped answering/)
  assert.ok(calls.every((call) => call.opts.agentType !== 'accio:house-elf' || call.opts.stallMs > 0))
})

test('S-019/3 a child waits for its parent and its slot goes to another story', async () => {
  const stories = [story('S-001'), story('S-002', { parents: ['S-001'] }), story('S-003')]
  const { calls } = await runWorkflow('brew', happy(stories, {
    'S-001 implement': async () => { await sleep(30); return { status: 'DONE' } },
  }))
  const order = labels(calls)
  assert.ok(order.indexOf('S-003 prepare') < order.indexOf('S-002 prepare'), order.join(', '))
  assert.ok(order.indexOf('S-001 outcome') < order.indexOf('S-002 prepare'), order.join(', '))
  assert.match(calls.find((call) => call.label === 'S-002 prepare').prompt, /--parent story\/S-001/)
})

test('S-019/4 a child of a BLOCKED parent never starts', async () => {
  const stories = [story('S-001'), story('S-002', { parents: ['S-001'] })]
  const { result, calls } = await runWorkflow('brew', happy(stories, {
    check: async () => ({ pass: false, failing: ['npm test'] }),
  }))
  assert.deepEqual(steps(calls, 'S-002'), [])
  assert.match(result, /S-001 Story S-001\s+BLOCKED/)
  assert.match(result, /S-002 Story S-002\s+NOT STARTED\s+its parent is blocked/)
  assert.match(calls.find((call) => call.label === 'S-001 outcome').prompt, /these checks fail: npm test/)
})

test('a blocked story\'s question goes to the main checkout, never into the worktree', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')], {
    check: async () => ({ pass: false, failing: ['npm test'] }),
  }))
  const prompt = calls.find((call) => call.label === 'S-001 outcome').prompt
  assert.match(prompt, /\.accio\/run\/questions\/S-001\.md in the main checkout/)
  assert.match(prompt, /never inside the worktree/)
})

test('S-019/5 a ledger skip counts as passed and nothing is re-run', async () => {
  const stories = [story('S-001')]
  const { result, calls } = await runWorkflow('brew', happy(stories, { check: async () => ({ skipped: true }) }))
  assert.deepEqual(steps(calls, 'S-001'), ['prepare', 'implement', 'check', 'outcome'])
  assert.match(calls.find((call) => call.label === 'S-001 outcome').prompt, /READY/)
  assert.match(result, /READY/)
})

test('S-019/6 a story a crash left in Doing resumes at check or prepare', async () => {
  const stories = [story('S-001', { resume: 'check' }), story('S-002', { resume: 'prepare' })]
  const { calls } = await runWorkflow('brew', happy(stories))
  assert.deepEqual(steps(calls, 'S-001'), ['check', 'package', 'examiner', 'professor', 'outcome'])
  assert.deepEqual(steps(calls, 'S-002'), ['prepare', 'implement', 'check', 'package', 'examiner', 'professor', 'outcome'])
  assert.match(calls[0].prompt, /--resume/)
})

test('S-019/7 the run returns the build table only', async () => {
  const stories = [story('S-001', { title: 'Password reset email' }), story('S-002', { title: 'Reset token expiry' })]
  const { result } = await runWorkflow('brew', happy(stories, {
    check: async (call, id) => (id === 'S-002' ? { pass: false, untagged: ['S-002/1'] } : { pass: true, failing: [] }),
  }))
  assert.equal(typeof result, 'string')
  assert.equal(result, [
    'Build finished: 2 stories',
    '  S-001 Password reset email  READY',
    '  S-002 Reset token expiry    BLOCKED      1 question for you',
    'Next: /accio:owl',
  ].join('\n'))
})

test('S-019/8 portkey takes the lock at load and releases it in finally, even when the run throws', async () => {
  const ok = await runWorkflow('brew', happy([story('S-001')]))
  assert.equal(ok.calls[0].label, 'load')
  assert.match(ok.calls[0].prompt, /take the lock/)
  assert.equal(ok.calls.at(-1).label, 'unlock')
  const seen = []
  await assert.rejects(runWorkflow('brew', async (call) => {
    seen.push(call.label)
    return happy([story('S-001')])(call)
  }, undefined, { throwInPhase: 'Build' }))
  assert.equal(seen.at(-1), 'unlock')
  const refused = await runWorkflow('brew', async (call) => (call.label === 'load'
    ? { locked: false, stories: [], error: 'a build is already running' } : { done: true }))
  assert.deepEqual(labels(refused.calls), ['load'])
  assert.match(refused.result, /Build didn't start: a build is already running/)
  const failedAfterLock = await runWorkflow('brew', async (call) => (call.label === 'load'
    ? { locked: true, stories: [], error: 'a story file is malformed' } : { done: true }))
  assert.deepEqual(labels(failedAfterLock.calls), ['load', 'unlock'])
  assert.match(failedAfterLock.result, /Build didn't start: a story file is malformed/)
  const silent = await runWorkflow('brew', async (call) => (call.label === 'load' ? null : { done: true }))
  assert.deepEqual(labels(silent.calls), ['load'])
  assert.match(silent.result, /goes stale/)
})

test('S-019/9 every step keeps the run lock fresh', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')]))
  assert.match(calls.find((call) => call.label === 'S-001 prepare').prompt, /accio-board move S-001 doing/)
  assert.match(calls.find((call) => call.label === 'S-001 outcome').prompt, /move it to review/)
  for (const name of ['prefect', 'house-elf']) {
    assert.match(readFileSync(join(AGENTS, `${name}.md`), 'utf8'), /accio-board refresh/, name)
  }
})

test('S-019/2 an implementer that returns BLOCKED or NEEDS_CONTEXT stops its story before the checks', async () => {
  const stories = [story('S-001'), story('S-002')]
  const { result, calls } = await runWorkflow('brew', happy(stories, {
    'S-001 implement': async () => ({ status: 'BLOCKED', report: '/run/S-001/build-report.md' }),
    'S-002 implement': async () => ({ status: 'NEEDS_CONTEXT', report: '/run/S-002/build-report.md' }),
  }))
  assert.deepEqual(steps(calls, 'S-001'), ['prepare', 'implement', 'outcome'])
  assert.deepEqual(steps(calls, 'S-002'), ['prepare', 'implement', 'judge', 'release', 'implement', 'outcome'])  // S-020/3, S-057/1
  assert.match(calls.find((call) => call.label === 'S-001 outcome').prompt, /report says why: \/run\/S-001\/build-report.md/)
  assert.equal((result.match(/BLOCKED/g) || []).length, 2)
})

test('S-019/5 prefect gets the worktree for the check and the outcome, also for a story resumed at check', async () => {
  const stories = [story('S-001'), story('S-002', { resume: 'check', worktree: '/wt/S-002' })]
  const { calls } = await runWorkflow('brew', happy(stories))
  for (const label of ['S-001 check', 'S-001 outcome']) {
    assert.match(calls.find((call) => call.label === label).prompt, /Worktree: \/wt\/S-001\./, label)
  }
  for (const label of ['S-002 check', 'S-002 outcome']) {
    assert.match(calls.find((call) => call.label === label).prompt, /Worktree: \/wt\/S-002\./, label)
  }
})

test('S-019/3 a child with two parents in this run waits for the next run; a parent outside the run never holds it', async () => {
  const stories = [story('S-003', { parents: ['S-001'] }), story('S-001'), story('S-002'),
    story('S-004', { parents: ['S-001', 'S-002'] }), story('S-005', { parents: ['S-099'] })]
  const { result, calls } = await runWorkflow('brew', happy(stories, {
    'S-001 implement': async () => { await sleep(20); return { status: 'DONE' } },
  }))
  const order = labels(calls)
  assert.ok(order.indexOf('S-001 outcome') < order.indexOf('S-003 prepare'), order.join(', '))
  assert.deepEqual(steps(calls, 'S-004'), [])
  assert.match(result, /S-004 Story S-004\s+NOT STARTED\s+it needs 2 stories from this run/)
  assert.deepEqual(steps(calls, 'S-005'), ['prepare', 'implement', 'check', 'package', 'examiner', 'professor', 'outcome'])
})

test('S-024/3 step 7 tells prefect to compute the ledger key', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')]))
  assert.match(calls.find((call) => call.label === 'S-001 outcome').prompt, /compute the ledger key as in step 3/)
})

test('S-019/7 an outcome the board did not take, or a check with no reasons, still reads plainly', async () => {
  const stories = [story('S-001'), story('S-002')]
  const { result, calls } = await runWorkflow('brew', happy(stories, {
    'S-001 outcome': async () => ({ done: false, error: 'move failed' }),
    'S-001 outcome retry': async () => ({ done: false, error: 'move failed' }),  // S-035: the retry fails too
    'S-002 check': async () => ({ pass: false }),
  }))
  assert.match(result, /S-001 Story S-001\s+READY\s+the board was not updated; the next brew resumes it/)
  assert.match(calls.find((call) => call.label === 'S-002 outcome').prompt, /failed without saying which/)
})

test('S-019/8 a load error after the lock builds nothing, even with stories listed', async () => {
  const { calls, result } = await runWorkflow('brew', async (call) => (call.label === 'load'
    ? { locked: true, stories: [story('S-001')], error: 'hooks verify failed' } : { done: true }))
  assert.deepEqual(labels(calls), ['load', 'unlock'])
  assert.match(result, /Build didn't start: hooks verify failed/)
})

test('S-019/3 stories that can never start are still reported, never dropped', async () => {
  const stories = [story('S-001', { parents: ['S-002'] }), story('S-002', { parents: ['S-001'] })]
  const { result, calls } = await runWorkflow('brew', happy(stories))
  assert.deepEqual(labels(calls), ['load', 'unlock'])
  assert.match(result, /S-001 Story S-001\s+NOT STARTED\s+its parent never finished/)
  assert.match(result, /S-002 Story S-002\s+NOT STARTED\s+its parent never finished/)
})

test('S-015/3 the load schema accepts wip with the stories, and portkey is told to reply with both', async () => {
  const { calls } = await runWorkflow('brew', async (call) => (call.label === 'load'
    ? { locked: true, wip: 2, stories: [] } : { done: true }))
  assert.match(calls[0].prompt, /"wip"/)
  const text = readFileSync(join(AGENTS, 'portkey.md'), 'utf8')
  assert.match(text, /"wip"/)
  assert.match(text, /\.stories/)
})

test('S-015/4 a load step that returns wip 1 never has two stories in progress at once', async () => {
  const stories = [story('S-001'), story('S-002'), story('S-003')]
  let active = 0
  let peak = 0
  const base = happy(stories)
  const { calls } = await runWorkflow('brew', async (call) => {
    if (call.label === 'load') return { locked: true, wip: 1, stories }
    const id = call.label.split(' ')[0]
    if (call.label === `${id} prepare`) { active += 1; peak = Math.max(peak, active); await sleep(5) }
    if (call.label === `${id} outcome`) active -= 1
    return base(call)
  })
  assert.equal(peak, 1)
  assert.equal(calls.filter((call) => call.label.endsWith(' prepare')).length, 3)
})

// --- S-034: check failures go to a fix round ----------------------------------------------------------------------

const FINDINGS = '.accio/run/S-001/check-findings.md'

test('S-034/5 failed checks start a fix round with --fix pointing at check-findings.md, and the re-check passes', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    'S-001 check': async () => ({ pass: false, failing: ['npm test'], findings: FINDINGS }),
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(0, 6), ['prepare', 'implement', 'check', 'fix-brief', 'fix', 'check'])
  const fixBrief = calls.find((call) => call.label === 'S-001 fix-brief r1')
  assert.match(fixBrief.prompt, new RegExp(`--fix ${FINDINGS.replaceAll('.', '\\.')}`))
  assert.match(result, /S-001 Story S-001\s+READY/)
})

test('S-034/5 each failing kind (untagged, weak test, out of bounds) goes to a fix round too', async () => {
  for (const reply of [{ untagged: ['S-001/2'] }, { weak_tests: ['a.py:1: x'] }, { out_of_bounds: ['x.py'] }]) {
    const { calls } = await runWorkflow('brew', happy([story('S-001')], {
      'S-001 check': async () => ({ pass: false, ...reply }),
    }))
    assert.ok(labels(calls).includes('S-001 fix r1'), JSON.stringify(reply))
  }
})

test('S-034/5 a main checkout change or a moved origin is no fix round: it blocks with a reason', async () => {
  const { calls, result } = await runWorkflow('brew', happy([story('S-001')], {
    check: async () => ({ pass: false, main_changed: ['src/x.py'], remote_moved: true }),
  }))
  assert.ok(!labels(calls).includes('S-001 fix r1'))
  assert.match(result, /S-001 Story S-001\s+BLOCKED/)
  assert.match(calls.find((call) => call.label === 'S-001 outcome').prompt, /main checkout changed during it: src\/x\.py/)
})

test('S-034/7 check fixes and review fixes share 2 rounds, then the story blocks', async () => {
  const stillFailing = async () => ({ pass: false, failing: ['npm test'] })
  const { calls, result } = await runWorkflow('brew', happy([story('S-001')], {
    check: stillFailing,
    'S-001 check r1': stillFailing,
    'S-001 check r2': stillFailing,
  }))
  assert.deepEqual(steps(calls, 'S-001'), ['prepare', 'implement', 'check', 'fix-brief', 'fix', 'check',
    'fix-brief', 'fix', 'check', 'outcome'])
  assert.match(result, /S-001 Story S-001\s+BLOCKED/)
  assert.match(calls.find((call) => call.label === 'S-001 outcome').prompt, /after 2 fix rounds/)
})

test('S-034/7 one check fix leaves one review fix round, and a second review failure blocks', async () => {
  const { calls, result } = await runWorkflow('brew', happy([story('S-001')], {
    'S-001 check': async () => ({ pass: false, untagged: ['S-001/1'] }),
    examiner: async (call, id) => fail(id, 'examiner'),
  }))
  assert.deepEqual(labels(calls).filter((label) => /^S-001 fix r/.test(label)), ['S-001 fix r1', 'S-001 fix r2'])
  assert.match(result, /S-001 Story S-001\s+BLOCKED/)
  assert.match(calls.find((call) => call.label === 'S-001 outcome').prompt, /after 2 fix rounds/)
})

test('S-034/8 brew.js never asks "Should it be fixed"', () => {
  const source = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'workflows', 'brew.js'), 'utf8')
  assert.doesNotMatch(source, /Should it be fixed/)
})

// A step that answers badly once, then well: one try is not enough, two are.
const flaky = (bad, good) => { let tries = 0; return async (call, id) => (tries++ === 0 ? bad : good(call, id)) }

for (const [step, agent, bad] of [
  ['prepare', 'portkey', null], ['prepare', 'portkey', { error: 'boom' }],
  ['check', 'prefect', null], ['check', 'prefect', { error: 'boom' }],
  ['package', 'portkey', { error: 'boom' }], ['examiner', 'examiner', null], ['outcome', 'prefect', { error: 'boom' }],
]) {
  test(`S-035/1 S-035/2 a ${agent} ${step} reply of ${JSON.stringify(bad)} is retried once, labelled "<ID> ${step} retry"`, async () => {
    const base = happy([story('S-001')])
    const { result, calls } = await runWorkflow('brew', happy([story('S-001')], { [step]: flaky(bad, base) }))
    assert.deepEqual(labels(calls).filter((label) => label.startsWith(`S-001 ${step}`)).slice(0, 2),
      [`S-001 ${step}`, `S-001 ${step} retry`])
    assert.match(result, /S-001 Story S-001\s+READY/)
  })
}

test('S-035/1 a headmaster that answers null once is asked again and its ruling is used', async () => {
  const base = happy([story('S-001')])
  let builds = 0
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    implement: async (call, id) => (builds++ === 0 ? { status: 'NEEDS_CONTEXT', report: 'r' } : base(call, id)),
    judge: flaky(null, base),
  }))
  assert.deepEqual(labels(calls).filter((label) => label.includes('judge')), ['S-001 judge', 'S-001 judge retry'])
  assert.match(result, /S-001 Story S-001\s+READY/)
})

test('S-035/3 a second null or {error} reply blocks the story with cause accio, with no third try', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], { check: async () => ({ error: 'boom' }) }))
  assert.deepEqual(labels(calls).filter((label) => label.includes('check')), ['S-001 check', 'S-001 check retry'])
  assert.match(result, /S-001 Story S-001\s+BLOCKED/)
  assert.match(calls.find((call) => call.label === 'S-001 outcome').prompt, /The cause is accio/)
})

test('S-035/3 a reviewer silent twice blocks with cause accio; a builder silence is not accio\'s', async () => {
  const reviewer = await runWorkflow('brew', happy([story('S-001')], { examiner: async () => null }))
  assert.match(reviewer.calls.find((call) => call.label === 'S-001 outcome').prompt, /The cause is accio/)
  const builder = await runWorkflow('brew', happy([story('S-001')], { implement: async () => null }))
  assert.deepEqual(labels(builder.calls).filter((label) => label.includes('implement')), ['S-001 implement'])
  assert.doesNotMatch(builder.calls.find((call) => call.label === 'S-001 outcome').prompt, /The cause is accio/)
})

test('S-057/1 after a ruling the claim is released before the second builder starts, in a build and in a fix round', async () => {
  let builds = 0
  let fixes = 0
  const { calls } = await runWorkflow('brew', happy([story('S-001')], {
    implement: async () => ({ status: (builds += 1) === 1 ? 'NEEDS_CONTEXT' : 'DONE', report: 'r' }),
    'S-001 examiner': async (call, id) => fail(id, 'examiner'),
    fix: async () => ({ status: (fixes += 1) === 1 ? 'NEEDS_CONTEXT' : 'DONE', report: 'r' }),
  }))
  const order = labels(calls)
  for (const label of ['S-001 release', 'S-001 release r1']) {
    const call = calls.find((each) => each.label === label)
    assert.match(call.prompt, /accio-brief S-001 --release/, label)
    assert.equal(call.opts.agentType, 'accio:portkey', label)
  }
  assert.deepEqual(order.filter((label) => /^S-001 (implement|judge|release)$/.test(label)),
    ['S-001 implement', 'S-001 judge', 'S-001 release', 'S-001 implement'])
  assert.deepEqual(order.filter((label) => /^S-001 (fix|judge|release) r1$/.test(label)),
    ['S-001 fix r1', 'S-001 judge r1', 'S-001 release r1', 'S-001 fix r1'])
})

test('S-057/1 a release that fails stops the story with an accio cause instead of a builder that cannot claim', async () => {
  let builds = 0
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    implement: async () => ({ status: (builds += 1) === 1 ? 'NEEDS_CONTEXT' : 'DONE', report: 'r' }),
    release: async () => ({ error: 'cannot write claims.json' }),
  }))
  assert.equal(calls.filter((call) => call.label === 'S-001 implement').length, 1)
  assert.match(result, /S-001 Story S-001\s+BLOCKED/)
  assert.match(calls.find((call) => call.label === 'S-001 outcome').prompt, /The cause is accio/)
})
