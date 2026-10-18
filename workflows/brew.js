export const meta = {
  name: 'brew',
  description: 'Build the ready stories: each in its own worktree, test-first, checked by scripts, then marked for review',
  whenToUse: 'After /accio:prophecy moved stories to Ready. Runs unattended; review the result with /accio:owl.',
  phases: [
    { title: 'Load', detail: 'take the run lock and list the stories to build' },
    { title: 'Build', detail: 'prepare, implement, check and record each story, at most 3 at once' },
    { title: 'Finish', detail: 'release the run lock' },
  ],
}

// accio's build (DESIGN § 3.4, § 12.6; decision 010). The script reads no files: accio's agents run accio's
// scripts and reply in JSON. At most WIP stories are in progress; a stacked child waits for its parents to reach
// READY and gives its slot to another story meanwhile, and never starts when a parent ends BLOCKED. A story a crash
// left in Doing resumes at check or prepare. portkey takes the run lock at load and releases it in `finally`;
// every step refreshes it (a board move, or prefect's and house-elf's `accio-board refresh`). The run returns the
// build table only. Review, the judge and fix rounds come in S-020; until then a story that passes its checks is
// READY.

const WIP = 3
const STALL_MS = 20 * 60 * 1000
const PORTKEY = 'accio:portkey'
const HOUSE_ELF = 'accio:house-elf'
const PREFECT = 'accio:prefect'
const IMPLEMENT_STATUSES = ['DONE', 'DONE_WITH_CONCERNS', 'NEEDS_CONTEXT', 'BLOCKED']

const STORY_SCHEMA = {
  type: 'object',
  properties: {
    id: { type: 'string' }, title: { type: 'string' }, track: { type: 'string' },
    parents: { type: 'array', items: { type: 'string' } }, resume: { type: ['string', 'null'] },
    worktree: { type: ['string', 'null'] },
  },
  required: ['id', 'title', 'track', 'parents', 'resume'],
}
const LOAD_SCHEMA = {
  type: 'object',
  properties: { locked: { type: 'boolean' }, stories: { type: 'array', items: STORY_SCHEMA }, error: { type: 'string' } },
  required: ['locked', 'stories'],
}
const PREPARE_SCHEMA = {
  type: 'object',
  properties: { worktree: { type: 'string' }, brief: { type: 'string' }, base: { type: 'string' }, error: { type: 'string' } },
}
const IMPLEMENT_SCHEMA = {
  type: 'object',
  properties: { status: { type: 'string', enum: IMPLEMENT_STATUSES }, head: { type: 'string' }, report: { type: 'string' } },
  required: ['status'],
}
const CHECK_SCHEMA = {
  type: 'object',
  properties: {
    pass: { type: 'boolean' }, skipped: { type: 'boolean' }, failing: { type: 'array', items: { type: 'string' } },
    out_of_bounds: { type: 'array', items: { type: 'string' } }, untagged: { type: 'array', items: { type: 'string' } },
    main_changed: { type: 'array', items: { type: 'string' } }, remote_moved: { type: 'boolean' },
    weak_tests: { type: 'array', items: { type: 'string' } }, error: { type: 'string' },
  },
}
const OUTCOME_SCHEMA = { type: 'object', properties: { done: { type: 'boolean' }, error: { type: 'string' } }, required: ['done'] }

// --- agents ---------------------------------------------------------------------------------------------------

async function call(prompt, opts) {
  // A stalled or dead agent gives null (or throws): the story then goes to Blocked with a plain question.
  try {
    return await agent(prompt, { phase: 'Build', ...opts })
  } catch (error) {
    return null
  }
}

function parentFlag(story) {
  return story.parents.length ? ` --parent story/${story.parents[story.parents.length - 1]}` : ''
}

function prepare(story) {
  return call(
    `Step 1, prepare story ${story.id}. Run, in order: \`accio-board move ${story.id} doing\`, ` +
      `\`accio-brief ${story.id}${parentFlag(story)}\`, \`accio-check ${story.id} snapshot\`. ` +
      'Reply with {worktree, brief, base} from accio-brief, or {error} if a script fails.',
    { agentType: PORTKEY, model: 'haiku', schema: PREPARE_SCHEMA, label: `${story.id} prepare`, stallMs: STALL_MS },
  )
}

function implement(story, prepared) {
  const model = story.track === 'feature' ? 'opus' : 'sonnet'
  return call(
    `Build story ${story.id} (${story.title}). Your brief is ${prepared.brief}; your worktree is ${prepared.worktree}. ` +
      'Run the claim command from the brief first, on its own.',
    { agentType: HOUSE_ELF, model, schema: IMPLEMENT_SCHEMA, label: `${story.id} implement`, stallMs: STALL_MS },
  )
}

function check(story, worktree) {
  return call(
    `Step 3, check story ${story.id}. Worktree: ${worktree}. Panel: ${story.track}. Follow your step 3. Reply ` +
      'with accio-check\'s JSON, or {"skipped": true} when the ledger says skip, or {error}.',
    { agentType: PREFECT, model: 'haiku', schema: CHECK_SCHEMA, label: `${story.id} check`, stallMs: STALL_MS },
  )
}

async function record(story, worktree, outcome, question) {
  const tail = outcome === 'READY'
    ? `It is READY: move it to review and record pass.`
    : `It is BLOCKED: move it to blocked, record fail, and write this question: ${question}`
  const reply = await call(
    `Step 7, outcome of story ${story.id}. Worktree: ${worktree}. Panel: ${story.track}. ${tail} ` +
      'Reply {"done": true} or {error}.',
    { agentType: PREFECT, model: 'haiku', schema: OUTCOME_SCHEMA, label: `${story.id} outcome`, stallMs: STALL_MS })
  const recorded = Boolean(reply && reply.done && !reply.error)
  const note = recorded ? '' : 'the board was not updated; the next brew resumes it'
  return { id: story.id, title: story.title, outcome, question: question || '', note }
}

// --- one story -------------------------------------------------------------------------------------------------

function checkQuestion(result) {
  const parts = [
    result.failing && result.failing.length && `these checks fail: ${result.failing.join(', ')}`,
    result.out_of_bounds && result.out_of_bounds.length && `it changed files outside the story: ${result.out_of_bounds.join(', ')}`,
    result.untagged && result.untagged.length && `these DoD lines have no tagged test: ${result.untagged.join(', ')}`,
    result.main_changed && result.main_changed.length && `the main checkout changed during it: ${result.main_changed.join(', ')}`,
    result.remote_moved && 'origin moved during it',
    result.weak_tests && result.weak_tests.length && `these tests miss a mutant: ${result.weak_tests.join(', ')}`,
  ].filter(Boolean)
  const why = parts.length ? parts.join('; ') : 'they failed without saying which (see its report)'
  return `The checks stopped it: ${why}. Should it be fixed and built again?`
}

async function runStory(story) {
  let worktree = story.worktree
  if (story.resume !== 'check') {
    const prepared = await prepare(story)
    if (!prepared || prepared.error || !prepared.brief) {
      const why = (prepared && prepared.error) || 'no answer'
      return record(story, worktree, 'BLOCKED', `Preparing it failed (${why}). Try again?`)
    }
    worktree = prepared.worktree
    const built = await implement(story, prepared)
    if (!built) {
      return record(story, worktree, 'BLOCKED', 'The implementer stopped answering for over 20 minutes; it may have ' +
        'waited on a permission question (see .accio/run/stuck.json). Build it again?')
    }
    if (built.status === 'BLOCKED' || built.status === 'NEEDS_CONTEXT') {
      return record(story, worktree, 'BLOCKED',
        `The implementer stopped (${built.status}); its report says why: ${built.report || 'none'}.`)
    }
  }
  const result = await check(story, worktree)
  if (!result || result.error) {
    const why = (result && result.error) || 'no answer'
    return record(story, worktree, 'BLOCKED', `The check step failed (${why}). Try again?`)
  }
  if (result.skipped || result.pass) {
    return record(story, worktree, 'READY')
  }
  return record(story, worktree, 'BLOCKED', checkQuestion(result))
}

// --- scheduling ------------------------------------------------------------------------------------------------

function parentState(story, inRun, outcomes) {
  const waiting = story.parents.filter((parent) => inRun.has(parent))
  if (waiting.length > 1) return 'two-parents'
  if (waiting.some((parent) => outcomes.has(parent) && outcomes.get(parent) !== 'READY')) return 'parent-blocked'
  return waiting.every((parent) => outcomes.get(parent) === 'READY') ? 'go' : 'wait'
}

async function schedule(stories) {
  const inRun = new Set(stories.map((story) => story.id))
  const outcomes = new Map()
  const rows = []
  const pending = [...stories]
  const running = new Map()
  while (pending.length || running.size) {
    for (const story of [...pending]) {
      if (running.size >= WIP) break
      const state = parentState(story, inRun, outcomes)
      if (state === 'wait') continue
      pending.splice(pending.indexOf(story), 1)
      if (state === 'parent-blocked' || state === 'two-parents') {
        const why = state === 'two-parents' ? 'it needs 2 stories from this run; it runs in the next one'
          : 'its parent is blocked'
        outcomes.set(story.id, 'NOT STARTED')
        rows.push({ id: story.id, title: story.title, outcome: 'NOT STARTED', question: '', note: why })
        continue
      }
      running.set(story.id, runStory(story).then((row) => ({ story, row })))
    }
    if (!running.size) {
      for (const story of pending) {
        rows.push({ id: story.id, title: story.title, outcome: 'NOT STARTED', question: '', note: 'its parent never finished' })
      }
      break
    }
    const { story, row } = await Promise.race(running.values())
    running.delete(story.id)
    outcomes.set(story.id, row.outcome)
    rows.push(row)
  }
  return rows
}

// --- the build table -------------------------------------------------------------------------------------------

function table(rows, note) {
  const width = Math.max(0, ...rows.map((row) => `${row.id} ${row.title}`.length))
  const lines = rows.map((row) => {
    const name = `${row.id} ${row.title}`.padEnd(width)
    const extra = [row.outcome === 'BLOCKED' ? '1 question for you' : '', row.note].filter(Boolean).join('; ')
    return `  ${name}  ${row.outcome.padEnd(13)}${extra}`.trimEnd()
  })
  const head = note || `Build finished: ${rows.length} ${rows.length === 1 ? 'story' : 'stories'}`
  const next = rows.length ? 'Next: /accio:owl' : ''
  return [head, ...lines, next].filter(Boolean).join('\n')
}

// --- the run ---------------------------------------------------------------------------------------------------

phase('Load')
const loaded = await call(
  'Step 0, load. Follow your step 0: take the lock, verify the hooks, list the stories with ' +
    '`accio-board ready --json --resume`, and take a fresh snapshot for each story resumed at check. ' +
    'Reply {"locked": true, "stories": [...]} with each story\'s id, title, track, parents, resume and worktree. ' +
    'If taking the lock fails, reply {"locked": false, "stories": [], "error": "..."}; if a script fails after ' +
    'the lock was taken, reply {"locked": true, "stories": [], "error": "..."}.',
  { agentType: PORTKEY, model: 'haiku', schema: LOAD_SCHEMA, label: 'load', phase: 'Load', stallMs: STALL_MS },
)
if (!loaded) {
  return table([], "Build didn't start: portkey didn't answer. If it took the run lock, the lock goes stale after " +
    '30 minutes, or release it with `accio-board unlock`.')
}
if (!loaded.locked) {
  return table([], `Build didn't start: ${loaded.error || 'the run lock was not taken'}`)
}
let rows = []
try {
  if (!loaded.error) {
    phase('Build')
    rows = await schedule(loaded.stories)
  }
} finally {
  phase('Finish')
  await call('Release the run lock: run `accio-board unlock`. Reply {"done": true} or {error}.',
    { agentType: PORTKEY, model: 'haiku', schema: OUTCOME_SCHEMA, label: 'unlock', phase: 'Finish', stallMs: STALL_MS })
}
const empty = loaded.error ? `Build didn't start: ${loaded.error}` : 'Nothing to build: no story is ready'
return table(rows, rows.length ? '' : empty)
