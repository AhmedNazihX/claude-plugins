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
  assert.match(prompt(calls, 'S-001 outcome'), /BLOCKED[\s\S]*after 2 fix rounds[\s\S]*findings-examiner\.md/)
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
    /accio-brief S-001 --fix \/run\/S-001\/findings-examiner\.md --fix \/run\/S-001\/findings-auror\.md/)
  assert.match(prompt(calls, 'S-001 package'), /accio-brief S-001 --review`/)
  assert.match(prompt(calls, 'S-001 package r1'), /accio-brief S-001 --review --since h0`/)
  for (const label of ['S-001 examiner r1', 'S-001 auror r1']) {
    assert.match(prompt(calls, label), /fix round 1/i, label)
    assert.match(prompt(calls, label), /only the fix diff/, label)
  }
  assert.doesNotMatch(prompt(calls, 'S-001 examiner'), /fix round/i)
})

test('S-020/3 an implementer that returns NEEDS_CONTEXT goes to headmaster, and builds again with the ruling', async () => {
  let builds = 0
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    implement: async () => ({ status: (builds += 1) === 1 ? 'NEEDS_CONTEXT' : 'DONE', report: '/run/S-001/report.md' }),
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(0, 4), ['prepare', 'implement', 'judge', 'implement'])
  assert.equal(calls.find((call) => call.label === 'S-001 judge').opts.agentType, 'accio:headmaster')
  assert.match(prompt(calls, 'S-001 judge'), /NEEDS_CONTEXT[\s\S]*\/run\/S-001\/report\.md/)
  assert.match(calls.filter((call) => call.label === 'S-001 implement')[1].prompt, /The story is right; the finding goes\./)
  assert.match(result, /READY/)
})

test('S-020/3 a finding that conflicts with the story goes to headmaster, and the ruling reaches the fix and re-review', async () => {
  let fixes = 0
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    'S-001 examiner': async (call, id) => fail(id, 'examiner'),
    fix: async () => ({ status: (fixes += 1) === 1 ? 'NEEDS_CONTEXT' : 'DONE', report: '/run/S-001/report.md' }),
  }))
  assert.deepEqual(steps(calls, 'S-001').slice(6, 12),
    ['fix-brief r1', 'fix r1', 'judge r1', 'fix r1', 'check r1', 'package r1'])
  assert.match(prompt(calls, 'S-001 judge r1'), /findings-examiner\.md/)
  assert.match(calls.find((call) => call.label === 'S-001 fix r1').prompt, /conflicts with the story[\s\S]*NEEDS_CONTEXT/)
  for (const call of calls.filter((each) => each.label === 'S-001 fix r1').slice(1).concat(
    calls.filter((each) => each.label === 'S-001 examiner r1'))) {
    assert.match(call.prompt, /The story is right; the finding goes\./, call.label)
  }
  assert.match(result, /READY/)
})

test('S-020/3 a second NEEDS_CONTEXT after a ruling blocks the story instead of judging again', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    implement: async () => ({ status: 'NEEDS_CONTEXT', report: '/run/S-001/report.md' }),
  }))
  assert.deepEqual(steps(calls, 'S-001'), ['prepare', 'implement', 'judge', 'implement', 'outcome'])
  assert.match(prompt(calls, 'S-001 outcome'), /BLOCKED[\s\S]*still needs context/)
  assert.match(result, /BLOCKED/)
})

test('S-020/4 a question from headmaster blocks the story with its question file, written once', async () => {
  const { result, calls } = await runWorkflow('brew', happy([story('S-001')], {
    implement: async () => ({ status: 'NEEDS_CONTEXT', report: '/run/S-001/report.md' }),
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
    fix: async () => ({ status: 'NEEDS_CONTEXT', report: '/run/S-001/report.md' }),
  }))
  for (const call of calls.filter((each) => !['load', 'unlock'].includes(each.label))) {
    assert.match(call.label, /^S-001 /)
  }
})

test('S-020 a reviewer that stops answering, or a failing re-check, blocks the story with a plain question', async () => {
  const stories = [story('S-001'), story('S-002')]
  const { result, calls } = await runWorkflow('brew', happy(stories, {
    'S-001 professor': async () => null,
    'S-002 examiner': async (call, id) => fail(id, 'examiner'),
    'S-002 check r1': async () => ({ pass: false, failing: ['npm test'] }),
  }))
  assert.match(prompt(calls, 'S-001 outcome'), /BLOCKED[\s\S]*professor stopped answering/)
  assert.deepEqual(steps(calls, 'S-002').slice(-3), ['fix r1', 'check r1', 'outcome'])
  assert.match(prompt(calls, 'S-002 outcome'), /these checks fail: npm test/)
  assert.equal((result.match(/BLOCKED/g) || []).length, 2)
})

test('S-020 a ledger skip is work that already passed review: no reviewer runs', async () => {
  const { calls } = await runWorkflow('brew', happy([story('S-001')], { check: async () => ({ skipped: true }) }))
  assert.deepEqual(steps(calls, 'S-001'), ['prepare', 'implement', 'check', 'outcome'])
})
