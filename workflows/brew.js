export const meta = {
  name: 'brew',
  description: 'Build the ready stories: each in its own worktree, test-first, checked by scripts, reviewed, then marked for your review',
  whenToUse: 'After /accio:prophecy moved stories to Ready. Runs unattended; review the result with /accio:owl.',
  phases: [
    { title: 'Load', detail: 'take the run lock and list the stories to build' },
    { title: 'Build', detail: 'prepare, implement, check, review, fix and record each story, at most 3 at once' },
    { title: 'Finish', detail: 'release the run lock' },
  ],
}

// accio's build (DESIGN § 3.4, § 12.6; decision 010). The script reads no files: accio's agents run accio's
// scripts and reply in JSON. At most WIP stories are in progress; a stacked child waits for its parents to reach
// READY and gives its slot to another story meanwhile, and never starts when a parent ends BLOCKED. A story a crash
// left in Doing resumes at check or prepare. portkey takes the run lock at load and releases it in `finally`;
// every step refreshes it (a board move, or prefect's and house-elf's `accio-board refresh`). The run returns the
// build table only.
// A story that passes its checks is reviewed by its panel (Quick: examiner alone; else examiner and professor;
// auror on a risky path, also when only a fix touches one). Findings get at most 2 fix rounds, each a fresh house-elf (one tier up in round 2), a
// re-check, and a re-review of only the fix diff by the reviewers that raised them, plus auror whenever the
// package is risky. A house-elf that returns
// NEEDS_CONTEXT, which includes a fix it refuses because the finding conflicts with the story, goes to headmaster:
// a ruling gets one more try, a question blocks the story. house-elf's `maxTurns` is the 2× budget stop (S-001).
// Every label starts with the story id: accio-cost ties usage to stories by it.

const WIP = 3
const STALL_MS = 20 * 60 * 1000
const MAX_FIX_ROUNDS = 2
const REVIEW_MODEL = 'sonnet'
const TIER_UP = { haiku: 'sonnet', sonnet: 'opus', opus: 'opus' }
const PORTKEY = 'accio:portkey'
const HOUSE_ELF = 'accio:house-elf'
const PREFECT = 'accio:prefect'
const HEADMASTER = 'accio:headmaster'
const QUESTIONS = '.accio/run/questions'
const IMPLEMENT_STATUSES = ['DONE', 'DONE_WITH_CONCERNS', 'NEEDS_CONTEXT', 'BLOCKED']
const SILENT = 'The implementer stopped answering: it hit its turn limit (accio\'s stop at 2× its token budget), ' +
  'or was silent for over 20 minutes, perhaps waiting on a permission question (see .accio/run/stuck.json). ' +
  'Build it again?'

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
const PACKAGE_SCHEMA = {
  type: 'object',
  properties: { package: { type: 'string' }, head: { type: 'string' }, risky: { type: 'boolean' }, error: { type: 'string' } },
}
const COUNT = { type: 'integer' }
const REVIEW_SCHEMA = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['pass', 'fail'] }, path: { type: 'string' },
    counts: { type: 'object', properties: { critical: COUNT, major: COUNT, minor: COUNT }, required: ['critical', 'major', 'minor'] },
  },
  required: ['verdict', 'counts', 'path'],
}
const JUDGE_SCHEMA = {
  type: 'object',
  properties: { kind: { type: 'string', enum: ['ruling', 'question'] }, text: { type: 'string' }, path: { type: ['string', 'null'] } },
  required: ['kind', 'text'],
}
const OUTCOME_SCHEMA = { type: 'object', properties: { done: { type: 'boolean' }, error: { type: 'string' } }, required: ['done'] }

// --- agents ---------------------------------------------------------------------------------------------------

async function call(prompt, opts) {
  // A stalled or dead agent gives null (or throws): the story then goes to Blocked with a plain question.
  try {
    return await agent(prompt, { phase: 'Build', stallMs: STALL_MS, ...opts })
  } catch (error) {
    return null
  }
}

const label = (story, step, round) => `${story.id} ${step}${round ? ` r${round}` : ''}`
const rulingNote = (ruling) => (ruling ? ` The judge ruled: ${ruling}` : '')
const addRuling = (earlier, ruling) => [earlier, ruling].filter(Boolean).join(' ')
// A step that ends the story; `asked` when headmaster already wrote the question file.
const stop = (question, asked = false) => ({ stop: true, question, asked })

function parentFlag(story) {
  return story.parents.length ? ` --parent story/${story.parents[story.parents.length - 1]}` : ''
}

function prepare(story) {
  return call(
    `Step 1, prepare story ${story.id}. Run, in order: \`accio-board move ${story.id} doing\`, ` +
      `\`accio-brief ${story.id}${parentFlag(story)}\`, \`accio-check ${story.id} snapshot\`. ` +
      'Reply with {worktree, brief, base} from accio-brief, or {error} if a script fails.',
    { agentType: PORTKEY, model: 'haiku', schema: PREPARE_SCHEMA, label: label(story, 'prepare') },
  )
}

function implement(story, prepared, model, ruling) {
  return call(
    `Build story ${story.id} (${story.title}). Your brief is ${prepared.brief}; your worktree is ${prepared.worktree}. ` +
      'Run the claim command from the brief first, on its own.' + rulingNote(ruling),
    { agentType: HOUSE_ELF, model, schema: IMPLEMENT_SCHEMA, label: label(story, 'implement') },
  )
}

function check(story, worktree, round) {
  return call(
    `Step 3, check story ${story.id}. Worktree: ${worktree}. Panel: ${story.track}. Follow your step 3. Reply ` +
      'with accio-check\'s JSON, or {"skipped": true} when the ledger says skip, or {error}.',
    { agentType: PREFECT, model: 'haiku', schema: CHECK_SCHEMA, label: label(story, 'check', round) },
  )
}

function judge(story, worktree, round, report, findings) {
  const about = findings.length
    ? ` It was fixing these findings and says one conflicts with the story: ${findings.join(', ')}.` : ''
  return call(
    `Step 5, judge story ${story.id}. The implementer returned NEEDS_CONTEXT; its report: ${report || 'none'}.` +
      `${about} The story: .accio/stories/${story.id}.md; worktree: ${worktree}. Rule from the story and the ` +
      `design, or, if only the user can answer, write one question to ${QUESTIONS}/${story.id}.md. The workflow ` +
      'records the outcome. Reply {kind, text, path}.',
    { agentType: HEADMASTER, model: REVIEW_MODEL, schema: JUDGE_SCHEMA, label: label(story, 'judge', round) },
  )
}

async function record(story, worktree, outcome, question, asked) {
  const blocked = asked
    ? `It is BLOCKED: move it to blocked and record fail. headmaster already wrote the question to ` +
      `${QUESTIONS}/${story.id}.md; don't add one.`
    : `It is BLOCKED: move it to blocked, record fail, and write this question: ${question}`
  const reply = await call(
    `Step 7, outcome of story ${story.id}. Worktree: ${worktree}. Panel: ${story.track}. ` +
      `${outcome === 'READY' ? 'It is READY: move it to review and record pass.' : blocked} ` +
      'Reply {"done": true} or {error}.',
    { agentType: PREFECT, model: 'haiku', schema: OUTCOME_SCHEMA, label: label(story, 'outcome') })
  const recorded = Boolean(reply && reply.done && !reply.error)
  const note = recorded ? '' : 'the board was not updated; the next brew resumes it'
  return { id: story.id, title: story.title, outcome, question: question || '', note }
}

// --- building: implement or fix, with the judge on NEEDS_CONTEXT ----------------------------------------------

function settle(reply, ruling) {
  if (!reply) return stop(SILENT)
  if (reply.status === 'BLOCKED') {
    return stop(`The implementer stopped (BLOCKED); its report says why: ${reply.report || 'none'}.`)
  }
  return { reply, ruling }
}

// `attempt(ruling)` runs a fresh house-elf, given the story's rulings so far. NEEDS_CONTEXT goes to headmaster once
// (S-020/3): a ruling gets one more try and holds for the rest of the story; a question stops the story, with
// headmaster's question file when it wrote one (S-020/4).
async function build(story, worktree, round, attempt, findings = [], earlier = '') {
  const first = await attempt(earlier)
  if (!first || first.status !== 'NEEDS_CONTEXT') return settle(first, earlier)
  const judged = await judge(story, worktree, round, first.report, findings)
  if (!judged || !judged.text) {
    return stop(`The implementer needs context (see ${first.report || 'its report'}) and the judge didn't answer. Try again?`)
  }
  if (judged.kind === 'question') return stop(judged.text, Boolean(judged.path))
  const ruling = addRuling(earlier, judged.text)
  const again = await attempt(ruling)
  if (again && again.status === 'NEEDS_CONTEXT') {
    return stop(`The implementer still needs context after the judge's ruling; its report says what: ${again.report || 'none'}.`)
  }
  return settle(again, ruling)
}

async function fixRound(story, worktree, round, findings, model, earlier) {
  const flags = findings.map((path) => ` --fix ${path}`).join('')
  const brief = await call(
    `Fix round ${round} of story ${story.id}: run \`accio-brief ${story.id}${flags}\`. Reply with its ` +
      '{worktree, brief, base}, or {error} if it fails.',
    { agentType: PORTKEY, model: 'haiku', schema: PREPARE_SCHEMA, label: label(story, 'fix-brief', round) })
  if (!brief || brief.error || !brief.brief) {
    return stop(`Writing the fix brief failed (${(brief && brief.error) || 'no answer'}). Try again?`)
  }
  return build(story, worktree, round, (ruling) => call(
    `Fix round ${round} of story ${story.id}. Your fix brief is ${brief.brief}; your worktree is ${worktree}. ` +
      'Run the claim command from the brief first, on its own. If a finding conflicts with the story (it asks ' +
      'for what the DoD rules out, or contradicts it), don\'t fix it: reply NEEDS_CONTEXT and name it in your ' +
      'report.' + rulingNote(ruling),
    { agentType: HOUSE_ELF, model, schema: IMPLEMENT_SCHEMA, label: label(story, 'fix', round) }), findings, earlier)
}

// --- checks and review -----------------------------------------------------------------------------------------

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

function checkStop(result) {
  if (!result || result.error) return stop(`The check step failed (${(result && result.error) || 'no answer'}). Try again?`)
  return result.skipped || result.pass ? null : stop(checkQuestion(result))
}

function panel(story, risky) {
  const base = story.track === 'quick' ? ['examiner'] : ['examiner', 'professor']
  return risky ? [...base, 'auror'] : base
}

async function packageFor(story, round, since) {
  const reply = await call(
    `Step 4, review package for story ${story.id}: run \`accio-brief ${story.id} --review` +
      `${since ? ` --since ${since}` : ''}\`. Reply with its JSON {package, head, risky}, or {error} if it fails.`,
    { agentType: PORTKEY, model: 'haiku', schema: PACKAGE_SCHEMA, label: label(story, 'package', round) })
  if (!reply || reply.error || !reply.package || !reply.head) {
    return stop(`Writing the review package failed (${(reply && reply.error) || 'no answer'}). Try again?`)
  }
  return reply
}

function reviewPrompt(story, name, pkg, round, ruling) {
  const quick = story.track === 'quick' && name === 'examiner'
    ? ' Quick track: no separate quality reviewer, so after the DoD also review the diff as professor does ' +
      '(correctness bugs, silent errors).' : ''
  const fix = round
    ? ` This is fix round ${round}: judge only the fix diff, and mark each of your earlier findings resolved or open.` : ''
  return `Step 4, review story ${story.id}. Your review package: ${pkg.package}.${quick}${fix}${rulingNote(ruling)} ` +
    'Reply {verdict, counts, path}.'
}

async function review(story, names, pkg, round, ruling) {
  const replies = await Promise.all(names.map((name) => call(reviewPrompt(story, name, pkg, round, ruling),
    { agentType: `accio:${name}`, model: REVIEW_MODEL, schema: REVIEW_SCHEMA, label: label(story, name, round) })))
  return names.map((name, index) => ({ name, reply: replies[index] }))
}

// Review, then at most MAX_FIX_ROUNDS fix rounds (S-020/1, /2, /5). Returns a stop, or {} when the story is READY.
async function reviewAndFix(story, worktree, model, earlier) {
  let pkg = await packageFor(story, 0, null)
  if (pkg.stop) return pkg
  let names = panel(story, pkg.risky)
  let ruling = earlier
  for (let round = 0; ; round += 1) {
    const verdicts = await review(story, names, pkg, round, ruling)
    const silent = verdicts.find((each) => !each.reply)
    if (silent) return stop(`Its reviewer ${silent.name} stopped answering for over 20 minutes. Review it again?`)
    const failing = verdicts.filter((each) => each.reply.verdict !== 'pass')
    if (!failing.length) return {}
    const findings = failing.map((each) => each.reply.path)
    if (round === MAX_FIX_ROUNDS) {
      return stop(`Findings remain after ${MAX_FIX_ROUNDS} fix rounds (${findings.join(', ')}). Fix them by hand, ` +
        'or change the story?')
    }
    const tier = round + 1 === MAX_FIX_ROUNDS ? TIER_UP[model] : model
    const fixed = await fixRound(story, worktree, round + 1, findings, tier, ruling)
    if (fixed.stop) return fixed
    ruling = fixed.ruling
    const failed = checkStop(await check(story, worktree, round + 1))
    if (failed) return failed
    pkg = await packageFor(story, round + 1, pkg.head)
    if (pkg.stop) return pkg
    names = failing.map((each) => each.name)
    if (pkg.risky && !names.includes('auror')) names.push('auror')  // the fix touched a risky path, or `risk` names security
  }
}

// --- one story -------------------------------------------------------------------------------------------------

async function runStory(story) {
  const model = story.track === 'feature' ? 'opus' : 'sonnet'
  const blocked = (worktree, ended) => record(story, worktree, 'BLOCKED', ended.question, ended.asked)
  let worktree = story.worktree
  let ruling = ''
  if (story.resume !== 'check') {
    const prepared = await prepare(story)
    if (!prepared || prepared.error || !prepared.brief) {
      const why = (prepared && prepared.error) || 'no answer'
      return record(story, worktree, 'BLOCKED', `Preparing it failed (${why}). Try again?`)
    }
    worktree = prepared.worktree
    const built = await build(story, worktree, 0, (ruling) => implement(story, prepared, model, ruling))
    if (built.stop) return blocked(worktree, built)
    ruling = built.ruling
  }
  const result = await check(story, worktree, 0)
  if (result && result.skipped && !result.error) return record(story, worktree, 'READY')  // passed review before
  const failed = checkStop(result)
  if (failed) return blocked(worktree, failed)
  const reviewed = await reviewAndFix(story, worktree, model, ruling)
  return reviewed.stop ? blocked(worktree, reviewed) : record(story, worktree, 'READY')
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
  const order = stories.map((story) => story.id)  // the table lists stories in load (dependency) order
  return rows.sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id))
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
  { agentType: PORTKEY, model: 'haiku', schema: LOAD_SCHEMA, label: 'load', phase: 'Load' },
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
    { agentType: PORTKEY, model: 'haiku', schema: OUTCOME_SCHEMA, label: 'unlock', phase: 'Finish' })
}
const empty = loaded.error ? `Build didn't start: ${loaded.error}` : 'Nothing to build: no story is ready'
return table(rows, rows.length ? '' : empty)
