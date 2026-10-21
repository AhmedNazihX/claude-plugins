// S-020: brew.js review, judge, fix rounds and budgets (DESIGN § 3.4 steps 4–6, § 7.1, § 8.6), driven by stub.mjs.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { runWorkflow, happy, story, fail, pass } from './stub.mjs'

const AGENTS = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'agents')
const NO_UI = { ui: false, preview: false, test_data: false }  // the package flags review.py gives a diff with no UI
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
    package: async (call) => ({ package: '/run/S-001/review-package.md', head: heads[call.label.slice(6)] || 'h2', risky: true, code: false, breaker: false, ...NO_UI }),
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
    package: async (call, id) => ({ package: `/run/${id}/review-package.md`, head: 'h', risky: call.label === 'S-001 package r1', code: false, breaker: false, ...NO_UI }),
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
  assert.deepEqual(steps(calls, 'S-001').slice(0, 5), ['prepare', 'implement', 'judge', 'release', 'implement'])
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
  assert.deepEqual(steps(calls, 'S-001').slice(6, 13),
    ['fix-brief r1', 'fix r1', 'judge r1', 'release r1', 'fix r1', 'check r1', 'package r1'])
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
  assert.deepEqual(steps(calls, 'S-001'), ['prepare', 'implement', 'judge', 'release', 'implement', 'outcome'])
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
    package: async (call, id) => ({ package: `/run/${id}/review-package.md`, head: 'h0', risky: ['S-003', 'S-004'].includes(id), code: false, breaker: false, ...NO_UI }),
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

const withCode = async (call, id) => ({ package: `/run/${id}/review-package.md`, head: 'h0', risky: false, code: true, breaker: true, ...NO_UI })
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

test('S-043/2 the package prompt asks prefect to return the code and breaker flags', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')]))
  assert.match(prompt(calls, 'S-001 package'), /\{package, head, risky, code, breaker, ui, preview, test_data\}/)
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
      package: async (call, id) => ({ package: `/run/${id}/review-package.md`, head: 'h0', risky: false, ...NO_UI, ...flags }),
    }))
    assert.deepEqual(steps(calls, 'S-001').slice(-2), ['professor', 'outcome'], JSON.stringify(flags))
  }
})

test('S-058/1 the package schema requires the code and breaker flags', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')]))
  const schema = calls.find((call) => call.label === 'S-001 package').opts.schema
  assert.ok(schema.required.includes('code'))
  assert.ok(schema.required.includes('breaker'))
})

test('S-058/1 a package reply without the flags is retried, not read as false', async () => {
  let tries = 0
  const { calls } = await runWorkflow('brew', happy([story('S-001')], {
    package: async (call, id) => (++tries === 1 ? { package: `/run/${id}/review-package.md`, head: 'h0', risky: false }
      : withCode(call, id)),
    boggart: async () => ({ breaks: [] }),
  }))
  assert.ok(steps(calls, 'S-001').includes('boggart'))
})

test('S-058/2 a boggart skip names the false flag in the story note', async () => {
  const cases = [[{ code: false, breaker: true }, /code/], [{ code: true, breaker: false }, /breaker/]]
  for (const [flags, word] of cases) {
    const { result } = await runWorkflow('brew', happy([story('S-001')], {
      package: async (call, id) => ({ package: `/run/${id}/review-package.md`, head: 'h0', risky: false, ...NO_UI, ...flags }),
    }))
    assert.match(result, /boggart skipped: [^;\n]*`?\w*`? flag is false/i, JSON.stringify(flags))
    assert.match(result, new RegExp(`boggart skipped:[^\\n]*${word.source}`), JSON.stringify(flags))
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
    'S-001 package r1c': async (call, id) => ({ package: `/run/${id}/p.md`, head: 'h1', risky: true, code: true, breaker: true, ...NO_UI }),
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

// --- S-047: mad-eye after boggart ----------------------------------------------------------------------------------

const withUi = (extra = {}) => async (call, id) => ({
  package: `/run/${id}/review-package.md`, head: 'h0', risky: false, code: false, breaker: false, ui: true, preview: true, test_data: true, ...extra,
})
const SEEN = { findings: [{ id: 'mad-eye-1', where: '/login', claim: 'shows a Sign in button', dod: 'S-001/1', failure: 'no button', screenshot: '/r/.accio/run/S-001/mad-eye/S-001-1.png' }] }
const WALK = ['preview-start', 'mad-eye', 'preview-stop']
const frontMatter = (name) => readFileSync(join(AGENTS, `${name}.md`), 'utf8').split('\n---\n')[0]
const README = join(AGENTS, '..', 'README.md')
const madEyeSection = () => readFileSync(README, 'utf8').split('## mad-eye')[1].split('\n## ')[0].replace(/\s+/g, ' ')

test('S-047/1 the package reply schema carries the ui, preview and test_data flags', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')]))
  const props = calls.find((call) => call.label === 'S-001 package').opts.schema.properties
  for (const key of ['ui', 'preview', 'test_data']) assert.equal(props[key].type, 'boolean', key)
})

test('S-061/4 a package reply without ui, preview or test_data is retried as a failed reply', async () => {
  const schema = (await runWorkflow('brew', happy([story('S-001')]))).calls.find((call) => call.label === 'S-001 package').opts.schema
  for (const key of ['ui', 'preview', 'test_data']) assert.ok(schema.required.includes(key), key)
  for (const missing of ['ui', 'preview', 'test_data']) {
    let tries = 0
    const { calls } = await runWorkflow('brew', happy([story('S-001')], {
      package: async (call, id) => {
        const reply = withUi()
        if (++tries === 1) delete reply[missing]
        return { ...reply, package: `/run/${id}/review-package.md` }
      },
    }))
    assert.ok(labels(calls).includes('S-001 package retry'), missing)
  }
})

test('S-061/5 brew.js tells portkey to match no glob and compute no flag', () => {
  const source = readFileSync(join(AGENTS, '..', 'workflows', 'brew.js'), 'utf8')
  const start = source.indexOf('async function packageFor')
  const body = source.slice(start, source.indexOf('\n}\n', start))
  assert.doesNotMatch(body, /ui_globs|config\.json|match/i)
})

test('S-047/2 a diff that touches no ui_globs file never calls mad-eye, or starts a preview', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')], { package: withUi({ ui: false }) }))
  assert.deepEqual(steps(calls, 'S-001').slice(-2), ['professor', 'outcome'])
  assert.ok(!types(calls, 'S-001').includes('accio:mad-eye'))
})

test('S-047/3 a UI diff with no preview in config logs a skip that names the preview', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], { package: withUi({ preview: false, test_data: false }) }))
  assert.deepEqual(steps(calls, 'S-001').slice(-2), ['professor', 'outcome'])
  assert.match(result, /S-001 Story S-001\s+READY\s+(?:boggart skipped[^;\n]*; )?mad-eye skipped: config\.json has no `preview`/)
})

test('S-047/3 a UI diff whose preview lacks test_data true logs a skip that names test_data', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], { package: withUi({ test_data: false }) }))
  assert.deepEqual(steps(calls, 'S-001').slice(-2), ['professor', 'outcome'])
  assert.match(result, /READY\s+(?:boggart skipped[^;\n]*; )?mad-eye skipped: config\.json preview has no `"test_data": true`/)
})

test('S-047/4 the missing browser tools outcome of S-044 logs a skip, and the preview still stops', async () => {
  const missing = [
    ['the agent says so', async () => ({ no_browser_tools: true })],
    ['the call errors', async () => ({ error: 'Error: No such tool available: mcp__plugin_playwright_playwright__browser_navigate' })],
  ]
  for (const [name, reply] of missing) {
    const { result, calls } = await runWorkflow('brew', happy([story('S-001')], { package: withUi(), 'mad-eye': reply }))
    assert.deepEqual(steps(calls, 'S-001').slice(-4), WALK.concat('outcome'), name)
    assert.match(result, /READY\s+(?:boggart skipped[^;\n]*; )?mad-eye skipped: the browser tools are missing from this session/, name)
  }
})

test('S-047/5 mad-eye runs between accio-preview start and stop, run by prefect, in that order', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')], { package: withUi() }))
  assert.deepEqual(steps(calls, 'S-001').slice(-4), WALK.concat('outcome'))
  assert.match(prompt(calls, 'S-001 preview-start'), /accio-preview S-001 start/)
  assert.match(prompt(calls, 'S-001 preview-stop'), /accio-preview S-001 stop/)
  assert.equal(calls.find((call) => call.label === 'S-001 preview-start').opts.agentType, 'accio:prefect')
  assert.equal(calls.find((call) => call.label === 'S-001 mad-eye').opts.agentType, 'accio:mad-eye')
  assert.equal(calls.find((call) => call.label === 'S-001 mad-eye').opts.model, 'sonnet')
})

test('S-047/6 mad-eye failing, erroring or throwing still stops the preview', async () => {
  const bad = [async () => null, async () => ({ error: 'it broke' }), async () => { throw new Error('boom') }]
  for (const reply of bad) {
    const { result, calls } = await runWorkflow('brew', happy([story('S-001')], { package: withUi(), 'mad-eye': reply }))
    assert.deepEqual(steps(calls, 'S-001').slice(-4), WALK.concat('outcome'))
    assert.match(result, /READY\s+(?:boggart skipped[^;\n]*; )?mad-eye skipped/)
  }
})

test('S-047/6 a preview that fails to start still gets a stop and no mad-eye call', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    package: withUi(), 'preview-start': async () => ({ done: false, error: 'port in use' }),
  }))
  assert.ok(!labels(calls).includes('S-001 mad-eye'))
  assert.ok(labels(calls).includes('S-001 preview-stop'))
  assert.match(result, /mad-eye skipped: the preview did not start \(port in use\)/)
})

test('S-047/7 mad-eye findings are written to mad-eye-findings.md and go to a fix round, then the fix diff is reviewed', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], { package: withUi(), 'mad-eye': async () => SEEN }))
  assert.deepEqual(steps(calls, 'S-001').slice(6), WALK.concat(['mad-eye-findings r1', 'fix-brief r1', 'fix r1', 'check r1',
    'package r1c', 'examiner r1', 'professor r1', 'outcome']))
  assert.match(prompt(calls, 'S-001 mad-eye-findings r1'), /\.accio\/run\/S-001\/mad-eye-findings\.md[\s\S]*no button/)
  assert.match(prompt(calls, 'S-001 fix-brief r1'), /accio-brief S-001 --fix \.accio\/run\/S-001\/mad-eye-findings\.md/)
  assert.match(result, /S-001 Story S-001\s+READY/)
})

test('S-047/7 findings that mad-eye still reports after two fix rounds block the story with a question', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    package: withUi(), 'mad-eye': async () => SEEN,
    examiner: async (call, id) => (call.label.endsWith(' r2') ? pass(id, 'examiner') : fail(id, 'examiner')),
  }))
  assert.match(prompt(calls, 'S-001 outcome'), /BLOCKED/)
  assert.match(result, /S-001 Story S-001\s+BLOCKED/)
})

test('S-047/8 mad-eye.md names Sonnet, lists the fixed browser tools and reads, has no edit tool, and logs in only with preview-login.json', () => {
  const text = readFileSync(join(AGENTS, 'mad-eye.md'), 'utf8')
  const front = frontMatter('mad-eye')
  assert.match(front, /^model: sonnet$/m)
  const tools = front.match(/^tools: (.*)$/m)[1].split(',').map((tool) => tool.trim())
  const prefix = 'mcp__plugin_playwright_playwright__browser_'
  assert.deepEqual(tools.filter((tool) => !tool.startsWith(prefix)), ['Read', 'Grep', 'Glob'])
  assert.deepEqual(tools.filter((tool) => tool.startsWith(prefix)).map((tool) => tool.slice(prefix.length)).sort(),
    ['click', 'close', 'console_messages', 'fill_form', 'hover', 'navigate', 'press_key', 'resize', 'select_option',
      'snapshot', 'take_screenshot', 'type', 'wait_for'])
  assert.ok(!tools.some((tool) => /Edit|Write|Bash|evaluate|run_code|file_upload/.test(tool)))
  assert.match(text, /only with the account in `\.accio\/run\/<ID>\/preview-login\.json`/)
  assert.match(text.replace(/\s+/g, ' '), /opt-in to the whole build/)
})

test('S-047/11 mad-eye.md tells it to save screenshots at an absolute path under .accio/run/<ID>/mad-eye/', async () => {
  const text = readFileSync(join(AGENTS, 'mad-eye.md'), 'utf8').replace(/\s+/g, ' ')
  assert.match(text, /absolute path inside the repo/)
  assert.match(text, /\.accio\/run\/<ID>\/mad-eye\/<line>\.png/)
  const { calls } = await runWorkflow('brew', happy([story('S-001')], { package: withUi() }))
  assert.match(prompt(calls, 'S-001 mad-eye'), /absolute path[\s\S]*\.accio\/run\/S-001\/mad-eye\//)
})

test('S-047/12 mad-eye.md tells it to take a full page snapshot before each click', () => {
  const text = readFileSync(join(AGENTS, 'mad-eye.md'), 'utf8').replace(/\s+/g, ' ')
  assert.match(text, /full page snapshot before each click/)
})

test('S-047/9 the README mad-eye section says test data and test keys, that test_data is the user\'s word, and env-var logins', () => {
  const section = madEyeSection()
  assert.match(section, /preview must use test data and test keys/)
  assert.match(section, /`test_data` is your word, and accio can't check it/)
  assert.match(section, /Login details come from environment variables/)
})

test('S-047/13 the README mad-eye section tells the user to start the Playwright MCP server with --allowed-origins', () => {
  assert.match(madEyeSection(), /--allowed-origins <preview origin>/)
})
