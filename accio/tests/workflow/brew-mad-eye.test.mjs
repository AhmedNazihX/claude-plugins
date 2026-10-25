// S-087: mad-eye says which DoD lines it checked and which it skipped, so a page that never loaded, a failed login
// or every line skipped can't pass as clean. Driven by stub.mjs, on a web preview and on a native app's screenshots.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { runWorkflow, happy, story } from './stub.mjs'

const AGENTS = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'agents')
const labels = (calls) => calls.map((call) => call.label)
const callOf = (calls, label) => calls.find((call) => call.label === label)
const flat = (text) => text.replace(/\s+/g, ' ')
const HEAD = 'a'.repeat(40)

const ui = (extra) => async (call, id) => ({ package: `/run/${id}/review-package.md`, head: HEAD, risky: false,
  code: false, breaker: false, ui: true, ...extra })
const WEB = { package: ui({ preview: true, test_data: true }) }
const NATIVE = {
  package: ui({ preview: false, test_data: false }),
  'evidence-plan': async () => ({ ui_evidence: true, takes_over_screen: false, steps_doc: 'docs/ui-walk.md', themes: [] }),
  'mad-eye-steps': async () => ({ steps: 'open main\n' }),
  evidence: async () => ({ ok: true, folder: '/r/.accio/run/S-001/ui-evidence', head: HEAD, screenshots: 1 }),
}
const WAYS = [['web preview', WEB], ['native screenshots', NATIVE]]
const run = (way, madEye) => runWorkflow('brew', happy([story('S-001')], { ...way, 'mad-eye': madEye }))
const NONE_CHECKED = /mad-eye checked no DoD line/

test('S-087/1 the mad-eye reply schema requires checked and skipped, arrays of DoD ids', async () => {
  for (const [name, way] of WAYS) {
    const { calls } = await run(way, async () => ({ findings: [], checked: ['S-001/1'], skipped: [] }))
    const schema = callOf(calls, 'S-001 mad-eye').opts.schema
    for (const key of ['checked', 'skipped']) {
      assert.ok(schema.required.includes(key), `${name}: ${key}`)
      assert.equal(schema.properties[key].type, 'array', `${name}: ${key}`)
      assert.equal(schema.properties[key].items.type, 'string', `${name}: ${key}`)
    }
  }
})

test('S-087/1 a mad-eye reply that checked no DoD line leaves a note naming the skipped lines, never a clean pass', async () => {
  for (const [name, way] of WAYS) {
    const { result, calls } = await run(way, async () => ({ findings: [], checked: [], skipped: ['S-001/1', 'S-001/2'] }))
    assert.match(result, /S-001 Story S-001\s+READY/, name)
    assert.match(result, /mad-eye checked no DoD line \(skipped S-001\/1, S-001\/2\)/, name)
    assert.match(callOf(calls, 'S-001 outcome').prompt, /brew-notes\.md[\s\S]*mad-eye checked no DoD line/, name)
  }
})

test('S-087/1 a mad-eye reply that checked nothing and skipped nothing still leaves the note', async () => {
  const { result } = await run(WEB, async () => ({ findings: [], checked: [], skipped: [] }))
  assert.match(result, /mad-eye checked no DoD line \(it named no line skipped either\)/)
})

test('S-087/1 a mad-eye reply that checked a line and found nothing leaves no note', async () => {
  for (const [name, way] of WAYS) {
    const { result } = await run(way, async () => ({ findings: [], checked: ['S-001/1'], skipped: ['S-001/2'] }))
    assert.doesNotMatch(result, NONE_CHECKED, name)
    assert.doesNotMatch(result, /mad-eye skipped/, name)
  }
})

test('S-087/1 findings with no checked line still go to a fix round', async () => {
  const seen = { findings: [{ id: 'mad-eye-1', where: '/login', claim: 'shows a button', dod: 'S-001/1', failure: 'no button' }],
    checked: [], skipped: [] }
  const { calls } = await run(WEB, async () => seen)
  assert.ok(labels(calls).includes('S-001 mad-eye-findings r1'))
})

test('S-087/2 a mad-eye reply without checked or skipped is retried, labelled "<ID> mad-eye retry"', async () => {
  for (const [name, way] of WAYS) {
    for (const missing of ['checked', 'skipped']) {
      const reply = { findings: [], checked: ['S-001/1'], skipped: [] }
      const { result, calls } = await run(way, async (call) => {
        if (call.label.endsWith('retry')) return reply
        const partial = { ...reply }
        delete partial[missing]
        return partial
      })
      assert.ok(labels(calls).includes('S-001 mad-eye retry'), `${name}: ${missing}`)
      assert.doesNotMatch(result, /mad-eye skipped|mad-eye checked no DoD line/, `${name}: ${missing}`)
    }
  }
})

test('S-087/2 a reply still without checked on the retry is never read as checked: it is a skip note', async () => {
  for (const [name, way] of WAYS) {
    const { result, calls } = await run(way, async () => ({ findings: [] }))
    assert.ok(labels(calls).includes('S-001 mad-eye retry'), name)
    assert.match(result, /S-001 Story S-001\s+READY\s+(?:boggart skipped[^;\n]*; )?mad-eye skipped: mad-eye gave no answer/, name)
  }
})

test('S-087/2 a reply that says why mad-eye could not look is not retried', async () => {
  const { calls } = await run(WEB, async () => ({ no_browser_tools: true, checked: [], skipped: ['S-001/1'] }))
  assert.ok(!labels(calls).includes('S-001 mad-eye retry'))
})

test('S-087/1 S-087/2 the prompts and mad-eye.md name checked and skipped and say what goes in each', async () => {
  for (const [name, way] of WAYS) {
    const { calls } = await run(way, async () => ({ findings: [], checked: ['S-001/1'], skipped: [] }))
    const asked = flat(callOf(calls, 'S-001 mad-eye').prompt)
    for (const key of ['findings', 'checked', 'skipped']) assert.match(asked, new RegExp(`\\b${key}\\b`), `${name}: ${key}`)
  }
  const text = flat(readFileSync(join(AGENTS, 'mad-eye.md'), 'utf8'))
  const reply = text.slice(text.indexOf('Reply with JSON only'))
  assert.match(reply, /"checked": \[/)
  assert.match(reply, /"skipped": \[/)
  assert.match(reply, /`checked`[^.]*DoD id[^.]*held or not/)
  assert.match(reply, /`skipped`[^.]*DoD id[^.]*couldn't check/)
  assert.match(reply, /page that never loaded|failed login/)
})
