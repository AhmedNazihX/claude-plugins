// S-020: brew.js review, judge, fix rounds and budgets (DESIGN § 3.4 steps 4–6, § 7.1, § 8.6), driven by stub.mjs.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { runWorkflow, happy, story, fail } from './stub.mjs'

const AGENTS = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'agents')
const labels = (calls) => calls.map((call) => call.label)
const steps = (calls, id) => labels(calls).filter((label) => label.startsWith(`${id} `)).map((label) => label.slice(id.length + 1))
const prompt = (calls, label) => calls.find((call) => call.label === label).prompt
const types = (calls, id) => calls.filter((call) => call.label.startsWith(`${id} `)).map((call) => call.opts.agentType)

test('S-020/1 findings that remain after 2 fix rounds block the story; a third round never runs', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    examiner: async (call, id) => fail(id, 'examiner'),
  }))
  assert.deepEqual(steps(calls, 'S-001'), ['prepare', 'implement', 'check', 'package', 'examiner', 'professor',
    'fix-brief r1', 'fix r1', 'check r1', 'package r1', 'examiner r1',
    'fix-brief r2', 'fix r2', 'check r2', 'package r2', 'examiner r2', 'outcome'])
  assert.match(result, /S-001 Story S-001\s+BLOCKED\s+1 question for you/)
  assert.match(prompt(calls, 'S-001 outcome'), /BLOCKED[\s\S]*after 2 fix rounds[\s\S]*examiner-findings\.md/)
})

test('S-020/1 a fix round that clears the findings makes the story READY', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    'S-001 professor': async (call, id) => fail(id, 'professor'),
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(-7),
    ['professor', 'fix-brief r1', 'fix r1', 'check r1', 'package r1', 'professor r1', 'outcome'])
  assert.match(prompt(calls, 'S-001 outcome'), /READY/)
  assert.match(result, /S-001 Story S-001\s+READY/)
})

test('S-020/2 a fix round re-runs only the reviewers that raised findings, on the fix diff only', async () => {
  const heads = { package: 'h0', 'package r1': 'h1' }
  const { calls } = await runWorkflow('brew', happy([story('S-001')], {
    package: async (call) => ({ package: '/run/S-001/review-package.md', head: heads[call.label.slice(6)] || 'h2', risky: true }),
    'S-001 examiner': async (call, id) => fail(id, 'examiner'),
    'S-001 auror': async (call, id) => fail(id, 'auror'),
  }))
  assert.deepEqual(steps(calls, 'S-001').filter((step) => step.endsWith(' r1')),
    ['fix-brief r1', 'fix r1', 'check r1', 'package r1', 'examiner r1', 'auror r1'])
  assert.match(prompt(calls, 'S-001 fix-brief r1'),
    /accio-brief S-001 --fix \/run\/S-001\/examiner-findings\.md --fix \/run\/S-001\/auror-findings\.md/)
  assert.match(prompt(calls, 'S-001 package'), /accio-brief S-001 --review`/)
  assert.match(prompt(calls, 'S-001 package r1'), /accio-brief S-001 --review --since h0`/)
  for (const label of ['S-001 examiner r1', 'S-001 auror r1']) {
    assert.match(prompt(calls, label), /fix round 1/i, label)
    assert.match(prompt(calls, label), /only the fix diff/, label)
  }
  assert.doesNotMatch(prompt(calls, 'S-001 examiner'), /fix round/i)
})

test('S-020/5 a fix diff that touches a risky path brings auror into the re-review', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001'), story('S-002')], {
    package: async (call, id) => ({ package: `/run/${id}/review-package.md`, head: 'h', risky: call.label === 'S-001 package r1' }),
    examiner: async (call, id) => (call.label.endsWith(' r1') ? { verdict: 'pass', counts: { critical: 0, major: 0, minor: 0 }, path: 'p' } : fail(id, 'examiner')),
  }))
  assert.deepEqual(steps(calls, 'S-001').filter((step) => step.endsWith(' r1')),
    ['fix-brief r1', 'fix r1', 'check r1', 'package r1', 'examiner r1', 'auror r1'])
  assert.deepEqual(steps(calls, 'S-002').filter((step) => step.endsWith(' r1')),
    ['fix-brief r1', 'fix r1', 'check r1', 'package r1', 'examiner r1'])
})

test('S-020/3 an implementer that returns NEEDS_CONTEXT goes to headmaster, and builds again with the ruling', async () => {
  let builds = 0
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    implement: async () => ({ status: (builds += 1) === 1 ? 'NEEDS_CONTEXT' : 'DONE', report: '/run/S-001/build-report.md' }),
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(0, 4), ['prepare', 'implement', 'judge', 'implement'])
  assert.equal(calls.find((call) => call.label === 'S-001 judge').opts.agentType, 'accio:headmaster')
  assert.match(prompt(calls, 'S-001 judge'), /NEEDS_CONTEXT[\s\S]*\/run\/S-001\/build-report\.md/)
  assert.match(calls.filter((call) => call.label === 'S-001 implement')[1].prompt, /The story is right; the finding goes\./)
  assert.match(result, /READY/)
})

test('S-020/3 a finding that conflicts with the story goes to headmaster, and the ruling reaches the fix and re-review', async () => {
  let fixes = 0
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    'S-001 examiner': async (call, id) => fail(id, 'examiner'),
    fix: async () => ({ status: (fixes += 1) === 1 ? 'NEEDS_CONTEXT' : 'DONE', report: '/run/S-001/build-report.md' }),
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(6, 12),
    ['fix-brief r1', 'fix r1', 'judge r1', 'fix r1', 'check r1', 'package r1'])
  assert.match(prompt(calls, 'S-001 judge r1'), /examiner-findings\.md/)
  assert.match(calls.find((call) => call.label === 'S-001 fix r1').prompt, /conflicts with the story[\s\S]*NEEDS_CONTEXT/)
  for (const call of calls.filter((each) => each.label === 'S-001 fix r1').slice(1).concat(
    calls.filter((each) => each.label === 'S-001 examiner r1'))) {
    assert.match(call.prompt, /The story is right; the finding goes\./, call.label)
  }
  assert.match(result, /READY/)
})

test('S-020/3 a second NEEDS_CONTEXT after a ruling blocks the story instead of judging again', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    implement: async () => ({ status: 'NEEDS_CONTEXT', report: '/run/S-001/build-report.md' }),
  }))
  assert.deepEqual(steps(calls, 'S-001'), ['prepare', 'implement', 'judge', 'implement', 'outcome'])
  assert.match(prompt(calls, 'S-001 outcome'), /BLOCKED[\s\S]*still needs context/)
  assert.match(result, /BLOCKED/)
})

test('S-020/3 a ruling holds for the rest of the story: the reviewers and every later fixer get it', async () => {
  let builds = 0
  const { calls } = await runWorkflow('brew', happy([story('S-001')], {
    implement: async () => ({ status: (builds += 1) === 1 ? 'NEEDS_CONTEXT' : 'DONE', report: '/run/S-001/build-report.md' }),
    examiner: async (call, id) => fail(id, 'examiner'),
  }))
  assert.deepEqual(labels(calls).filter((each) => each.includes('judge')), ['S-001 judge'])
  for (const label of ['S-001 examiner', 'S-001 professor', 'S-001 fix r1', 'S-001 examiner r1', 'S-001 fix r2']) {
    assert.match(prompt(calls, label), /The story is right; the finding goes\./, label)
  }
})

test('S-036/2 the judge is told to write run/<ID>/ruling-r<N>.md and to return dismisses; the dismissed ids reach the later steps', async () => {
  let fixes = 0
  const { calls } = await runWorkflow('brew', happy([story('S-001')], {
    'S-001 examiner': async (call, id) => fail(id, 'examiner'),
    fix: async () => ({ status: (fixes += 1) === 1 ? 'NEEDS_CONTEXT' : 'DONE', report: '/run/S-001/build-report.md' }),
    judge: async () => ({ kind: 'ruling', text: 'The story is right.', dismisses: ['F-2'], path: null }),
  }))
  const judge = calls.find((call) => call.label === 'S-001 judge r1')
  assert.match(judge.prompt, /\.accio\/run\/S-001\/ruling-r1\.md/)
  assert.match(judge.prompt, /dismisses/)
  assert.deepEqual(Object.keys(judge.opts.schema.properties).sort(), ['dismisses', 'kind', 'path', 'text'])
  assert.match(calls.filter((call) => call.label === 'S-001 fix r1')[1].prompt, /F-2/)
  assert.match(calls.find((call) => call.label === 'S-001 examiner r1').prompt, /F-2/)
})

test('S-036/2 headmaster is told to return dismisses and write the ruling file', () => {
  const text = readFileSync(join(AGENTS, 'headmaster.md'), 'utf8')
  assert.match(text, /dismisses/)
  assert.match(text, /ruling-r<N>\.md/)
})

test('S-036/1 each block says its cause, code, accio or decision, as the first line of the question file', async () => {
  const cases = [
    ['code', { examiner: async (call, id) => fail(id, 'examiner') }],
    ['accio', { check: async () => ({ error: 'boom' }) }],
    ['decision', {
      implement: async () => ({ status: 'NEEDS_CONTEXT', report: 'r' }),
      judge: async () => ({ kind: 'question', text: 'Email or SMS?', path: null }),
    }],
  ]
  for (const [cause, overrides] of cases) {
    const { calls } = await runWorkflow('brew', happy([story('S-001')], overrides))
    assert.match(prompt(calls, 'S-001 outcome'), new RegExp(`first line[^.]*\\b${cause}\\b`), cause)
  }
})

test('S-036/1 a question headmaster wrote itself also gets the cause as its first line', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')], {
    implement: async () => ({ status: 'NEEDS_CONTEXT', report: 'r' }),
    judge: async () => ({ kind: 'question', text: 'Email or SMS?', path: '.accio/run/questions/S-001.md' }),
  }))
  assert.match(prompt(calls, 'S-001 outcome'), /first line[^.]*\bdecision\b/)
})

test('S-020/4 a question with no question file is written by prefect instead', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')], {
    implement: async () => ({ status: 'NEEDS_CONTEXT', report: '/run/S-001/build-report.md' }),
    judge: async () => ({ kind: 'question', text: 'Email or SMS for the reset?', path: null }),
  }))
  assert.match(prompt(calls, 'S-001 outcome'), /never inside the worktree: Email or SMS for the reset\?/)
})

test('S-020/4 a question from headmaster blocks the story with its question file, written once', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    implement: async () => ({ status: 'NEEDS_CONTEXT', report: '/run/S-001/build-report.md' }),
    judge: async () => ({ kind: 'question', text: 'Email or SMS for the reset?', path: '.accio/run/questions/S-001.md' }),
  }))
  assert.deepEqual(steps(calls, 'S-001'), ['prepare', 'implement', 'judge', 'outcome'])
  assert.match(prompt(calls, 'S-001 judge'), /\.accio\/run\/questions\/S-001\.md/)
  const outcome = prompt(calls, 'S-001 outcome')
  assert.match(outcome, /BLOCKED/)
  assert.match(outcome, /headmaster already wrote the question/)
  assert.doesNotMatch(outcome, /write this question/)
  assert.match(result, /S-001 Story S-001\s+BLOCKED\s+1 question for you/)
})

test('S-020/5 the panel: Quick gets one combined reviewer, Story two, and a risky path adds auror', async () => {
  const stories = [story('S-001', { track: 'quick' }), story('S-002'), story('S-003', { track: 'feature' }),
    story('S-004', { track: 'quick' })]
  const { calls } = await runWorkflow('brew', happy(stories, {
    package: async (call, id) => ({ package: `/run/${id}/review-package.md`, head: 'h0', risky: ['S-003', 'S-004'].includes(id) }),
  }))
  const reviewers = (id) => types(calls, id).filter((type) => /examiner|professor|auror/.test(type))
  assert.deepEqual(reviewers('S-001'), ['accio:examiner'])
  assert.match(prompt(calls, 'S-001 examiner'), /Quick track: no separate quality reviewer/)
  assert.deepEqual(reviewers('S-002'), ['accio:examiner', 'accio:professor'])
  assert.doesNotMatch(prompt(calls, 'S-002 examiner'), /Quick track/)
  assert.deepEqual(reviewers('S-003'), ['accio:examiner', 'accio:professor', 'accio:auror'])
  assert.deepEqual(reviewers('S-004'), ['accio:examiner', 'accio:auror'])
  for (const call of calls.filter((each) => / (examiner|professor|auror)$/.test(each.label))) {
    assert.match(call.prompt, /\/run\/S-00\d\/review-package\.md/, call.label)
    assert.equal(call.opts.model, 'sonnet', call.label)
  }
})

test('S-020/6 house-elf has a turn limit, and a fixer that stops without a reply blocks the story', async () => {
  const front = readFileSync(join(AGENTS, 'house-elf.md'), 'utf8').split('\n---\n')[0]
  assert.match(front, /^maxTurns: [1-9]\d*$/m)
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    'S-001 examiner': async (call, id) => fail(id, 'examiner'),
    fix: async () => null,
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(-3), ['fix-brief r1', 'fix r1', 'outcome'])
  assert.match(prompt(calls, 'S-001 outcome'), /BLOCKED[\s\S]*turn limit[\s\S]*2× its token budget/)
  assert.match(result, /BLOCKED/)
})

test('S-020/6 each fix round uses a fresh house-elf, one tier up in round 2', async () => {
  const stories = [story('S-001'), story('S-002', { track: 'feature' })]
  const { calls } = await runWorkflow('brew', happy(stories, { examiner: async (call, id) => fail(id, 'examiner') }))
  const model = (label) => calls.find((call) => call.label === label).opts.model
  assert.deepEqual(['S-001 implement', 'S-001 fix r1', 'S-001 fix r2'].map(model), ['sonnet', 'sonnet', 'opus'])
  assert.deepEqual(['S-002 implement', 'S-002 fix r1', 'S-002 fix r2'].map(model), ['opus', 'opus', 'opus'])
  for (const label of ['S-001 fix r1', 'S-001 fix r2']) {
    const call = calls.find((each) => each.label === label)
    assert.equal(call.opts.agentType, 'accio:house-elf')
    assert.match(call.prompt, /\/run\/S-001\/fix-brief\.md/)
  }
})

test('S-020 every agent of a story is labelled with its id first, for accio-cost', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')], {
    examiner: async (call, id) => fail(id, 'examiner'),
    fix: async () => ({ status: 'NEEDS_CONTEXT', report: '/run/S-001/build-report.md' }),
  }))
  for (const call of calls.filter((each) => !['load', 'unlock'].includes(each.label))) {
    assert.match(call.label, /^S-001 /)
  }
})

test('S-020 a reviewer that stops answering, or a failing re-check, blocks the story with a plain question', async () => {
  const stories = [story('S-001'), story('S-002')]
  const { result, calls } = await runWorkflow('brew', happy(stories, {
    'S-001 professor': async () => null,
    'S-001 professor retry': async () => null,  // S-035: the retry is silent too
    'S-002 examiner': async (call, id) => fail(id, 'examiner'),
    'S-002 check r1': async () => ({ pass: false, failing: ['npm test'] }),
    'S-002 check r2': async () => ({ pass: false, failing: ['npm test'] }),
  }))
  assert.match(prompt(calls, 'S-001 outcome'), /BLOCKED[\s\S]*code reviewer \(professor\) stopped answering/)
  assert.deepEqual(steps(calls, 'S-002').slice(-3), ['fix r2', 'check r2', 'outcome'])
  assert.match(prompt(calls, 'S-002 outcome'), /these checks fail: npm test/)
  assert.equal((result.match(/BLOCKED/g) || []).length, 2)
})

test('S-020 a ledger skip is work that already passed review: no reviewer runs', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')], { check: async () => ({ skipped: true }) }))
  assert.deepEqual(steps(calls, 'S-001'), ['prepare', 'implement', 'check', 'outcome'])
})

// --- S-043: boggart after review -----------------------------------------------------------------------------------

const withCode = async (call, id) => ({ package: `/run/${id}/review-package.md`, head: 'h0', risky: false, code: true, breaker: true })
const entry = (extra = {}) => ({
  file: 'r1.py', verdict: 'kept', reason: 'failed an assertion on head in both runs', claim: 'it resets', source: 'S-001/1',
  in_dod: true, ...extra,
})
const verdicts = (...repros) => async () => ({ skipped: false, repros })
const found = async () => ({ breaks: [{ file: 'r1.py', claim: 'it resets', source: 'S-001/1', verdict: 'kept' }], questions: [] })
const SETUP = 'still fails on head: failed with a setup error (ImportError), not a break'
const LOADS_NOT = { reason: SETUP, cant_load: true }  // breaker.py sets cant_load only for a setup error on head
const FIXED = 'passes on head after the fix round'

test('S-043/1 the package reply schema carries the code flag next to risky', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')]))
  const props = calls.find((call) => call.label === 'S-001 package').opts.schema.properties
  assert.equal(props.code.type, 'boolean')
  assert.equal(props.risky.type, 'boolean')
})

test('S-043/2 a diff with code that passes review goes to boggart, then prefect runs accio-break verify', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    package: withCode, boggart: found, verify: verdicts(entry({ verdict: 'dropped' })),
  }))
  assert.deepEqual(steps(calls, 'S-001'), ['prepare', 'implement', 'check', 'package', 'examiner', 'professor',
    'boggart', 'verify', 'outcome'])
  assert.equal(calls.find((call) => call.label === 'S-001 boggart').opts.agentType, 'accio:boggart')
  assert.match(prompt(calls, 'S-001 boggart'), /\/run\/S-001\/review-package\.md/)
  assert.equal(calls.find((call) => call.label === 'S-001 verify').opts.agentType, 'accio:prefect')
  assert.match(prompt(calls, 'S-001 verify'), /accio-break S-001 verify/)
  assert.match(result, /S-001 Story S-001\s+READY/)
})

test('S-043/2 boggart finding nothing means no verify and no fix round', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')], { package: withCode, boggart: async () => ({ breaks: [] }) }))
  assert.deepEqual(steps(calls, 'S-001').slice(-2), ['boggart', 'outcome'])
})

test('S-043/3 a kept break that touches a DoD line starts a fix round with boggart-findings.md', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    package: withCode, boggart: found,
    'S-001 verify': verdicts(entry()),
    'S-001 verify r1': verdicts(entry({ verdict: 'fixed', reason: FIXED })),
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(6), ['boggart', 'verify', 'boggart-findings r1', 'fix-brief r1', 'fix r1',
    'check r1', 'package r1c', 'examiner r1', 'professor r1', 'verify r1', 'outcome'])
  assert.match(prompt(calls, 'S-001 boggart-findings r1'), /\.accio\/run\/S-001\/boggart-findings\.md[\s\S]*r1\.py/)
  assert.match(prompt(calls, 'S-001 fix-brief r1'), /accio-brief S-001 --fix \.accio\/run\/S-001\/boggart-findings\.md/)
  assert.match(result, /S-001 Story S-001\s+READY/)
})

test('S-043/4 a kept break outside the DoD starts no fix round; owl logs it from the verdicts', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    package: withCode, boggart: found, verify: verdicts(entry({ in_dod: false, source: 'src/a.py:9' })),
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(-3), ['boggart', 'verify', 'outcome'])
  assert.match(result, /S-001 Story S-001\s+READY\s+boggart: 1 break outside the DoD, logged for owl/)
})

test('S-043/5 a docs-only diff, or a config with no breaker command, never calls boggart', async () => {
  for (const flags of [{ code: false, breaker: true }, { code: true, breaker: false }, { code: false, breaker: false }]) {
    const { calls } = await runWorkflow('brew', happy([story('S-001')], {
      package: async (call, id) => ({ package: `/run/${id}/review-package.md`, head: 'h0', risky: false, ...flags }),
    }))
    assert.deepEqual(steps(calls, 'S-001').slice(-2), ['professor', 'outcome'], JSON.stringify(flags))
  }
})

test('S-043/6 a kept in-DoD break that survives both fix rounds blocks the story with its repro', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    package: withCode, boggart: found, verify: verdicts(entry()),
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(6), ['boggart', 'verify',
    'boggart-findings r1', 'fix-brief r1', 'fix r1', 'check r1', 'package r1c', 'examiner r1', 'professor r1', 'verify r1',
    'boggart-findings r2', 'fix-brief r2', 'fix r2', 'check r2', 'package r2c', 'examiner r2', 'professor r2', 'verify r2',
    'outcome'])
  assert.match(prompt(calls, 'S-001 outcome'), /BLOCKED[\s\S]*\.accio\/run\/S-001\/boggart\/repros\/r1\.py[\s\S]*it resets/)
  assert.match(result, /S-001 Story S-001\s+BLOCKED\s+1 question for you/)
})

test('S-043/6 a fix round spent on review leaves one for a kept in-DoD break, and then it blocks', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')], {
    package: withCode, boggart: found, verify: verdicts(entry()),
    'S-001 examiner': async (call, id) => fail(id, 'examiner'),
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(-13), ['examiner r1', 'package r1b', 'boggart', 'verify',
    'boggart-findings r2', 'fix-brief r2', 'fix r2', 'check r2', 'package r2c', 'examiner r2', 'professor r2', 'verify r2',
    'outcome'])
  assert.match(prompt(calls, 'S-001 outcome'), /BLOCKED[\s\S]*r1\.py/)
})

test('S-043/8 a repro that fails to load after a fix round gets one boggart turn for its imports, then verify again', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    package: withCode, boggart: found,
    'S-001 verify': verdicts(entry()),
    'S-001 verify r1': verdicts(entry(LOADS_NOT)),
    'S-001 verify-repair r1': verdicts(entry({ verdict: 'fixed', reason: FIXED })),
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(-5), ['professor r1', 'verify r1', 'boggart-repair r1', 'verify-repair r1', 'outcome'])
  const repair = prompt(calls, 'S-001 boggart-repair r1')
  assert.match(repair, /r1\.py/)
  assert.match(repair, /imports or setup/)
  assert.match(repair, /never[^.]*claim[^.]*source[^.]*expected value/i)
  assert.equal(calls.find((call) => call.label === 'S-001 boggart-repair r1').opts.agentType, 'accio:boggart')
  assert.match(result, /READY/)
})

test('S-043/8 a repro that still cannot load is logged for owl and starts no fix round', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    package: withCode, boggart: found,
    'S-001 verify': verdicts(entry()),
    'S-001 verify r1': verdicts(entry(LOADS_NOT)),
    'S-001 verify-repair r1': verdicts(entry(LOADS_NOT)),
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(-5), ['professor r1', 'verify r1', 'boggart-repair r1', 'verify-repair r1', 'outcome'])
  assert.equal(steps(calls, 'S-001').filter((step) => step.startsWith('fix r')).length, 1)
  assert.match(result, /S-001 Story S-001\s+READY\s+boggart: 1 repro can't load, logged for owl/)
})

test('S-043/8 a kept break whose reason text says setup error but has no cant_load is a break, not a repro that cannot load', async () => {
  const onBase = entry({ reason: 'failed an assertion on head in both runs; the code under test isn\'t on base (setup error there)' })
  const { calls } = await runWorkflow('brew', happy([story('S-001')], {
    package: withCode, boggart: found, verify: verdicts(onBase),
  }))
  assert.ok(!labels(calls).some((label) => label.includes('boggart-repair')))
  assert.ok(labels(calls).includes('S-001 boggart-findings r1'))
})

test('S-043/3 after a fix round for a boggart break passes its checks, its diff is reviewed before verify runs again', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')], {
    package: withCode, boggart: found,
    'S-001 verify': verdicts(entry()),
    'S-001 verify r1': verdicts(entry({ verdict: 'fixed', reason: FIXED })),
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(-7), ['fix r1', 'check r1', 'package r1c', 'examiner r1', 'professor r1',
    'verify r1', 'outcome'])
  assert.match(prompt(calls, 'S-001 package r1c'), /--since h0/)
})

test('S-043/3 the review of a boggart fix adds auror when the fix diff is risky', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')], {
    'S-001 package': withCode,
    'S-001 package r1c': async (call, id) => ({ package: `/run/${id}/p.md`, head: 'h1', risky: true, code: true, breaker: true }),
    boggart: found,
    'S-001 verify': verdicts(entry()),
    'S-001 verify r1': verdicts(entry({ verdict: 'fixed', reason: FIXED })),
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(-6), ['package r1c', 'examiner r1', 'professor r1', 'auror r1', 'verify r1', 'outcome'])
})

test('S-043 a boggart or verify step that gives no answer does not block the story', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001'), story('S-002')], {
    package: withCode,
    'S-001 boggart': async () => null, 'S-001 boggart retry': async () => null,
    'S-002 boggart': found, 'S-002 verify': async () => null, 'S-002 verify retry': async () => null,
  }))
  assert.match(result, /S-001 Story S-001\s+READY\s+boggart gave no answer/)
  assert.match(result, /S-002 Story S-002\s+READY\s+boggart's verify gave no answer/)
  assert.ok(labels(calls).includes('S-001 boggart retry'))
})
