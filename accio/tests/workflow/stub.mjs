// Runs a workflow script the way the Workflow runtime does: its body inside an async function, with `agent()`,
// `phase()` and the other globals given as arguments. The fake `agent()` answers from a responder, so tests can
// script each step's reply, delay, stall (null) or failure (a throw), and read every call afterwards.
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const WORKFLOWS = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'workflows')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// The runtime retries a reply that doesn't fit the schema and gives up with an error; the stub rejects it at once.
function fits(value, schema) {
  if (!schema || value === null || value === undefined) return true
  const types = [].concat(schema.type || [])
  const kind = Array.isArray(value) ? 'array' : value === null ? 'null' : Number.isInteger(value) ? 'integer' : typeof value
  if (types.length && !types.includes(kind) && !(kind === 'integer' && types.includes('number'))) return false
  if (schema.enum && !schema.enum.includes(value)) return false
  if (kind === 'array') return value.every((item) => fits(item, schema.items))
  if (kind !== 'object') return true
  if ((schema.required || []).some((key) => !(key in value))) return false
  return Object.entries(schema.properties || {}).every(([key, sub]) => !(key in value) || fits(value[key], sub))
}

export async function runWorkflow(name, responder, args, options = {}) {
  const source = readFileSync(join(WORKFLOWS, `${name}.js`), 'utf8').replace(/^export const meta = /, 'const meta = ')
  const calls = []
  const agent = async (prompt, opts = {}) => {
    const call = { prompt, opts, label: opts.label, started: calls.length }
    calls.push(call)
    try {
      const reply = await responder(call)
      if (!fits(reply, opts.schema)) throw new Error(`${opts.label}: the reply doesn't fit the schema`)
      return reply
    } finally {
      call.finished = true
    }
  }
  const noop = () => {}
  const phase = (title) => {
    if (title === options.throwInPhase) throw new Error(`phase ${title} failed`)
  }
  const run = new AsyncFunction('agent', 'parallel', 'pipeline', 'log', 'phase', 'args', 'budget', source)
  const parallel = (thunks) => Promise.all(thunks.map((thunk) => thunk().catch(() => null)))
  const result = await run(agent, parallel, null, noop, phase, args, { total: null, spent: () => 0, remaining: () => Infinity })
  return { result, calls }
}

// The default happy-path replies, by step; a test overrides what it needs, by full label (`S-001 examiner r1`) or by
// step (`examiner`). A label is `<ID> <step>`, plus ` r<n>` in a fix round.
export function happy(stories, overrides = {}) {
  return async (call) => {
    const [id, step] = call.label.includes(' ') ? call.label.split(' ') : [null, call.label]
    const override = overrides[call.label] || overrides[step]
    if (override) return override(call, id)
    if (step === 'load') return { locked: true, stories }
    if (step === 'prepare') return { worktree: `/wt/${id}`, brief: `/run/${id}/brief.md`, base: 'abc' }
    if (step === 'implement' || step === 'fix') return { status: 'DONE', head: 'def', report: `/run/${id}/build-report.md` }
    if (step === 'check') return { pass: true, skipped: false, failing: [] }
    if (step === 'package') return { package: `/run/${id}/review-package.md`, head: 'h0', risky: false, code: false, breaker: false, ui: false, preview: false, test_data: false }
    if (REVIEWERS.includes(step)) return pass(id, step)
    if (step === 'fix-brief') return { worktree: `/wt/${id}`, brief: `/run/${id}/fix-brief.md`, base: 'abc' }
    if (step === 'judge') return { kind: 'ruling', text: 'The story is right; the finding goes.', path: null }
    if (step === 'mad-eye') return { findings: [], checked: [`${id}/1`], skipped: [] }  // S-087: it checked a line
    return { done: true }
  }
}

const REVIEWERS = ['examiner', 'professor', 'auror']
const counts = (major) => ({ critical: 0, major, minor: 0 })
export const pass = (id, reviewer) => ({ verdict: 'pass', counts: counts(0), path: `/run/${id}/${reviewer}-findings.md` })
export const fail = (id, reviewer) => ({ verdict: 'fail', counts: counts(1), path: `/run/${id}/${reviewer}-findings.md` })

export const story = (id, extra = {}) => ({ id, title: `Story ${id}`, track: 'story', parents: [], resume: null, ...extra })
