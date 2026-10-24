export const meta = {
  name: 'brew',
  description: 'Build (brew): builds the ready stories: each in its own worktree, test-first, checked by scripts, reviewed, then marked for your review',
  whenToUse: 'After /accio:prophecy moved stories to Ready. Runs unattended; review the result with /accio:owl.',
  phases: [
    { title: 'Load', detail: 'take the run lock and list the stories to build' },
    { title: 'Build', detail: 'prepare, implement, check, review, fix and record each story, at most 3 at once' },
    { title: 'Finish', detail: 'release the run lock' },
  ],
}

// accio's build (DESIGN § 3.4, § 12.6; decision 010). The script reads no files: accio's agents run accio's
// scripts and reply in JSON. At most `wip` (from config.json) stories are in progress; a stacked child waits for its parents to reach
// READY and gives its slot to another story meanwhile, and never starts when a parent ends BLOCKED. A story a crash
// left in Doing resumes at check or prepare. portkey takes the run lock at load and releases it in `finally`;
// every step refreshes it (a board move, or prefect's and house-elf's `accio-board refresh`). The run returns the
// build table only.
// Failed checks (a command, an untagged DoD line, a weak test, an out-of-bounds file) go to a fix round with
// prefect's check-findings.md, not to the user; check fixes and review fixes share MAX_FIX_ROUNDS. A change in the
// main checkout or at origin can't be fixed that way and blocks.
// A story that passes its checks is reviewed by its panel (Quick: examiner alone; else examiner and professor;
// auror on a risky path, also when only a fix touches one). Findings get at most 2 fix rounds, each a fresh house-elf (one tier up in round 2), a
// re-check, and a re-review of only the fix diff by the reviewers that raised them, plus auror whenever the
// package is risky. A house-elf that returns
// NEEDS_CONTEXT, which includes a fix it refuses because the finding conflicts with the story, goes to headmaster:
// a ruling gets one more try, a question blocks the story. house-elf's `maxTurns` is the 2× budget stop (S-001).
// After review passes, a story whose diff has code (the package's `code` and `breaker` flags) goes to boggart, with
// prefect running `accio-break <ID> verify` (S-043; see "boggart" below).
// After boggart, a story whose diff touches `ui_globs` (and whose config has a `preview` with `test_data: true`) goes to
// mad-eye between `accio-preview <ID> start` and `stop`; its findings go to a fix round (S-047; see "mad-eye" below).
// With `ui_evidence` instead (a native app), mad-eye judges screenshots from `accio-preview <ID> evidence` (S-068).
// Every label starts with the story id: accio-cost ties usage to stories by it.

const DEFAULT_WIP = 3  // used only when the load reply carries no usable wip
const STALL_MS = 20 * 60 * 1000
const MAX_FIX_ROUNDS = 2
const REVIEW_MODEL = 'sonnet'
const TIER_UP = { haiku: 'sonnet', sonnet: 'opus', opus: 'opus' }
const PORTKEY = 'accio:portkey'
const HOUSE_ELF = 'accio:house-elf'
const PREFECT = 'accio:prefect'
const HEADMASTER = 'accio:headmaster'
const BOGGART = 'accio:boggart'
const MAD_EYE = 'accio:mad-eye'
const QUESTIONS = '.accio/run/questions'
const IN_MAIN = 'in the main checkout (your working folder), never inside the worktree'  // curfew refuses the worktree copy
const ROLES = { examiner: 'spec reviewer', professor: 'code reviewer', auror: 'security reviewer' }
const IMPLEMENT_STATUSES = ['DONE', 'DONE_WITH_CONCERNS', 'NEEDS_CONTEXT', 'BLOCKED']
const SILENT = 'The builder (house-elf) stopped answering: it hit its turn limit (accio\'s stop at 2× its token budget), ' +
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
  properties: {
    locked: { type: 'boolean' }, wip: { type: 'integer' },
    stories: { type: 'array', items: STORY_SCHEMA }, error: { type: 'string' },
  },
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
    findings: { type: 'string' }, check_status: { type: 'object' },
  },
}
const PACKAGE_SCHEMA = {
  type: 'object',
  properties: {
    package: { type: 'string' }, head: { type: 'string' }, risky: { type: 'boolean' }, error: { type: 'string' },
    code: { type: 'boolean' }, breaker: { type: 'boolean' },  // the diff has code; config.json has a `breaker` command
    ui: { type: 'boolean' }, preview: { type: 'boolean' }, test_data: { type: 'boolean' },  // the diff touches `ui_globs`; config has a `preview`, with `test_data: true`
  },
  required: ['code', 'breaker', 'ui', 'preview', 'test_data'],  // a reply without them is retried, never read as false (S-058, S-061)
}
const BREAK_SCHEMA = {
  type: 'object',
  properties: { breaks: { type: 'array', items: { type: 'object' } }, questions: { type: 'array', items: { type: 'string' } } },
}
const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    skipped: { type: 'boolean' }, error: { type: 'string' },
    repros: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          file: { type: 'string' }, verdict: { type: 'string' }, reason: { type: 'string' }, claim: { type: 'string' },
          source: { type: 'string' }, in_dod: { type: 'boolean' }, cant_load: { type: 'boolean' },
        },
      },
    },
  },
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
  properties: {
    kind: { type: 'string', enum: ['ruling', 'question'] }, text: { type: 'string' }, path: { type: ['string', 'null'] },
    dismisses: { type: 'array', items: { type: 'string' } },
  },
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

const failed = (reply) => !reply || Boolean(reply.error)
// The cause of a block, written as the first line of its question file (S-036/1): `code` (the story's code or checks
// failed), `accio` (accio's own failure) or `decision` (only the user can answer).
const CODE = 'code'
const ACCIO = 'accio'
const DECISION = 'decision'

// accio's own agents (portkey, prefect, the reviewers, headmaster) get one more try on a null or {error} reply, labelled
// "<ID> <step> retry" so accio-cost ties it to the story (S-035/1, /2). The second reply stands, whatever it is.
async function callRetry(prompt, opts) {
  const first = await call(prompt, opts)
  if (!failed(first)) return first
  return call(prompt, { ...opts, label: `${opts.label} retry` })
}

const label = (story, step, round) => `${story.id} ${step}${round ? ` r${round}` : ''}`
const rulingNote = (ruling) => (ruling ? ` The judge ruled: ${ruling}` : '')
const addRuling = (earlier, ruling) => [earlier, ruling].filter(Boolean).join(' ')
// A step that ends the story; `asked` when headmaster already wrote the question file.
const stop = (question, asked = false, cause = CODE) => ({ stop: true, question, asked, cause })
const accioStop = (question) => stop(question, false, ACCIO)

function parentFlag(story) {
  return story.parents.length ? ` --parent story/${story.parents[story.parents.length - 1]}` : ''
}

function prepare(story) {
  return callRetry(
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
  return callRetry(
    `Step 3, check story ${story.id}. Worktree: ${worktree}. Panel: ${story.track}. Follow your step 3. Reply ` +
      'with accio-check\'s JSON, or {"skipped": true} when the ledger says skip, or {error}.',
    { agentType: PREFECT, model: 'haiku', schema: CHECK_SCHEMA, label: label(story, 'check', round) },
  )
}

function judge(story, worktree, round, report, findings) {
  const about = findings.length
    ? ` It was fixing these findings and says one conflicts with the story: ${findings.join(', ')}.` : ''
  return callRetry(
    `Step 5, judge story ${story.id}. The implementer returned NEEDS_CONTEXT; its report: ${report || 'none'}.` +
      `${about} The story: .accio/stories/${story.id}.md; worktree: ${worktree}. Rule from the story and the ` +
      `design, or, if only the user can answer, write one question to ${QUESTIONS}/${story.id}.md ${IN_MAIN}. ` +
      `Also write your ruling or question to .accio/run/${story.id}/ruling-r${round || 0}.md ${IN_MAIN}. The workflow ` +
      'records the outcome. Reply {kind, text, path, dismisses}, with dismisses the ids of the findings you rule out ' +
      '(an empty list when none).',
    { agentType: HEADMASTER, model: REVIEW_MODEL, schema: JUDGE_SCHEMA, label: label(story, 'judge', round) },
  )
}

async function record(story, worktree, outcome, question, asked, cause = CODE, extra = '') {
  const first = `Make the first line of the question file exactly \`${cause}\` (the cause).`
  const blocked = asked
    ? `It is BLOCKED: move it to blocked and record fail. headmaster already wrote the question to ` +
      `${QUESTIONS}/${story.id}.md; don't add one. ${first}`
    : `It is BLOCKED: move it to blocked, record fail, and write this question to ` +
      `${QUESTIONS}/${story.id}.md ${IN_MAIN}: ${question}. ${first}`
  const why = cause === ACCIO ? ` The cause is ${cause}: it is accio's own failure, not the story's.` : ''
  const reply = await callRetry(
    `Step 7, outcome of story ${story.id}. Worktree: ${worktree}. Panel: ${story.track}. ` +
      'First compute the ledger key as in step 3 (the same worktree and panel). ' +
      `${outcome === 'READY' ? 'It is READY: move it to review and record pass.' : blocked}${why} ` +
      'Reply {"done": true} or {error}.',
    { agentType: PREFECT, model: 'haiku', schema: OUTCOME_SCHEMA, label: label(story, 'outcome') })
  const recorded = Boolean(reply && reply.done && !reply.error)
  const note = recorded ? extra : [extra, 'the board was not updated; the next brew resumes it'].filter(Boolean).join('; ')
  return { id: story.id, title: story.title, outcome, question: question || '', cause, note }
}

// --- building: implement or fix, with the judge on NEEDS_CONTEXT ----------------------------------------------

function settle(reply, ruling) {
  if (!reply) return stop(SILENT)
  if (reply.status === 'BLOCKED') {
    return stop(`The builder (house-elf) stopped (BLOCKED); its report says why: ${reply.report || 'none'}.`)
  }
  return { reply, ruling }
}

// The ruling as the later steps read it: its text, and which findings it dismisses (S-036/2).
function rulingText(judged) {
  const dismissed = judged.dismisses && judged.dismisses.length ? ` Dismissed findings: ${judged.dismisses.join(', ')}.` : ''
  return `${judged.text}${dismissed}`
}

// A builder after a ruling gets no new brief, so its story's earlier claim is released first (S-057/1); else its
// `accio-claim` is refused as held by the builder before it.
function releaseClaim(story, round) {
  return callRetry(
    `Release the claim of story ${story.id}: run \`accio-brief ${story.id} --release\`. Reply {"done": true} or {error}.`,
    { agentType: PORTKEY, model: 'haiku', schema: OUTCOME_SCHEMA, label: label(story, 'release', round) })
}

// `attempt(ruling)` runs a fresh house-elf, given the story's rulings so far. NEEDS_CONTEXT goes to headmaster once
// (S-020/3): a ruling gets one more try and holds for the rest of the story; a question stops the story, with
// headmaster's question file when it wrote one (S-020/4).
async function build(story, worktree, round, attempt, findings = [], earlier = '') {
  const first = await attempt(earlier)
  if (!first || first.status !== 'NEEDS_CONTEXT') return settle(first, earlier)
  const judged = await judge(story, worktree, round, first.report, findings)
  if (!judged || !judged.text) {
    return accioStop(`The builder (house-elf) needs context (see ${first.report || 'its report'}) and the judge (headmaster) didn't answer. Try again?`)
  }
  if (judged.kind === 'question') return stop(judged.text, Boolean(judged.path), DECISION)
  const ruling = addRuling(earlier, rulingText(judged))
  const released = await releaseClaim(story, round)
  if (failed(released)) {
    return accioStop(`Releasing the story's claim before the second builder failed (${(released && released.error) || 'no answer'}). Try again?`)
  }
  const again = await attempt(ruling)
  if (again && again.status === 'NEEDS_CONTEXT') {
    return stop(`The builder (house-elf) still needs context after the judge's (headmaster's) ruling; its report says what: ${again.report || 'none'}.`)
  }
  return settle(again, ruling)
}

async function fixRound(story, worktree, round, findings, model, earlier) {
  const flags = findings.map((path) => ` --fix ${path}`).join('')
  const brief = await callRetry(
    `Fix round ${round} of story ${story.id}: run \`accio-brief ${story.id}${flags}\`. Reply with its ` +
      '{worktree, brief, base}, or {error} if it fails.',
    { agentType: PORTKEY, model: 'haiku', schema: PREPARE_SCHEMA, label: label(story, 'fix-brief', round) })
  if (!brief || brief.error || !brief.brief) {
    return accioStop(`Writing the fix brief failed (${(brief && brief.error) || 'no answer'}). Try again?`)
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
  return `the checks stopped it: ${why}`
}

const hasAny = (list) => Boolean(list && list.length)

// null when the checks passed or were skipped; a stop for a broken check step or a failure no fix round can undo (the
// main checkout or origin changed); else {fix: path}, the findings file for a fix round (S-034/5).
function checkStop(story, result) {
  if (failed(result)) return accioStop(`The check step failed (${(result && result.error) || 'no answer'}). Try again?`)
  if (result.skipped || result.pass) return null
  const fixable = hasAny(result.failing) || hasAny(result.out_of_bounds) || hasAny(result.untagged) || hasAny(result.weak_tests)
  if (!fixable || hasAny(result.main_changed) || result.remote_moved) {
    return stop(`${checkQuestion(result)}. A fix round can't undo that: fix it by hand, or change the story?`)
  }
  return { fix: result.findings || `.accio/run/${story.id}/check-findings.md`, why: checkQuestion(result) }
}

const tierFor = (model, fixes) => (fixes === MAX_FIX_ROUNDS ? TIER_UP[model] : model)

// Check, and while the checks fail run a fix round and check again. `fixes` counts the rounds used so far, check and
// review fixes together (S-034/7). Returns {fixes, ruling, skipped}, or a stop.
async function checkAndFix(story, worktree, model, fixes, earlier) {
  const result = await check(story, worktree, fixes)
  const failed = checkStop(story, result)
  if (!failed) return { fixes, ruling: earlier, skipped: Boolean(result.skipped) }
  if (!failed.fix) return failed
  if (fixes >= MAX_FIX_ROUNDS) {
    return stop(`Findings remain after ${MAX_FIX_ROUNDS} fix rounds: ${failed.why}. Fix them by hand, or change the story?`)
  }
  const fixed = await fixRound(story, worktree, fixes + 1, [failed.fix], tierFor(model, fixes + 1), earlier)
  if (fixed.stop) return fixed
  return checkAndFix(story, worktree, model, fixes + 1, fixed.ruling)
}

function panel(story, risky) {
  const base = story.track === 'quick' ? ['examiner'] : ['examiner', 'professor']
  return risky ? [...base, 'auror'] : base
}

async function packageFor(story, round, since) {  // `round` only labels the step
  const reply = await callRetry(
    `Step 4, review package for story ${story.id}: run \`accio-brief ${story.id} --review` +
      `${since ? ` --since ${since}` : ''}\`. Reply with its JSON {package, head, risky, code, breaker, ui, preview, test_data} (copy every flag as given), or {error} if it fails.`,
    { agentType: PORTKEY, model: 'haiku', schema: PACKAGE_SCHEMA, label: label(story, 'package', round) })
  if (!reply || reply.error || !reply.package || !reply.head) {
    return accioStop(`Writing the review package failed (${(reply && reply.error) || 'no answer'}). Try again?`)
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
  const replies = await Promise.all(names.map((name) => callRetry(reviewPrompt(story, name, pkg, round, ruling),
    { agentType: `accio:${name}`, model: REVIEW_MODEL, schema: REVIEW_SCHEMA, label: label(story, name, round) })))
  return names.map((name, index) => ({ name, reply: replies[index] }))
}

// Review, then at most MAX_FIX_ROUNDS fix rounds (S-020/1, /2, /5), then boggart (S-043). Returns a stop, or what
// boggart left ({note}) when the story is READY.
async function reviewAndFix(story, worktree, model, earlier, usedFixes) {
  const whole = await packageFor(story, 0, null)  // the whole story's package: its `code` and `breaker` flags decide whether boggart runs
  if (whole.stop) return whole
  const reviewed = await reviewLoop(story, worktree, model, earlier, usedFixes, whole, panel(story, whole.risky), 0)
  if (reviewed.stop) return reviewed
  const broken = await boggartStage(story, worktree, model, reviewed.ruling, reviewed.fixes, whole, reviewed.head)
  if (broken.stop) return broken
  const state = {
    fixes: broken.fixes === undefined ? reviewed.fixes : broken.fixes,
    ruling: broken.ruling === undefined ? reviewed.ruling : broken.ruling,
    head: broken.head || reviewed.head,
  }
  const seen = await madEyeStage(story, worktree, model, state, whole)
  if (seen.stop) return seen
  return { note: [broken.note, seen.note].filter(Boolean).join('; ') }
}

// The review rounds for `first`, a package: review, and while a reviewer fails run a fix round and review the fix diff.
// Returns a stop, or {fixes, ruling, head} (head: the commit the last review judged).
async function reviewLoop(story, worktree, model, earlier, usedFixes, first, firstNames, startRound) {
  let pkg = first
  let names = firstNames
  let ruling = earlier
  let fixes = usedFixes
  for (let round = startRound; ; round += 1) {
    const verdicts = await review(story, names, pkg, round, ruling)
    const silent = verdicts.find((each) => failed(each.reply))
    if (silent) return accioStop(`The ${ROLES[silent.name]} (${silent.name}) stopped answering for over 20 minutes. Review it again?`)
    const failing = verdicts.filter((each) => each.reply.verdict !== 'pass')
    if (!failing.length) return { fixes, ruling, head: pkg.head }
    const findings = failing.map((each) => each.reply.path)
    if (fixes >= MAX_FIX_ROUNDS) {
      return stop(`Findings remain after ${MAX_FIX_ROUNDS} fix rounds (${findings.join(', ')}). Fix them by hand, ` +
        'or change the story?')
    }
    fixes += 1
    const fixed = await fixRound(story, worktree, fixes, findings, tierFor(model, fixes), ruling)
    if (fixed.stop) return fixed
    const rechecked = await checkAndFix(story, worktree, model, fixes, fixed.ruling)
    if (rechecked.stop) return rechecked
    ruling = rechecked.ruling
    fixes = rechecked.fixes
    pkg = await packageFor(story, round + 1, pkg.head)
    if (pkg.stop) return pkg
    names = failing.map((each) => each.name)
    if (pkg.risky && !names.includes('auror')) names.push('auror')  // the fix touched a risky path, or `risk` names security
  }
}

// --- boggart: tries to break a reviewed story (S-043) ----------------------------------------------------------
// After the reviewers pass a story whose diff has code (and config.json has a `breaker` command), boggart writes repros
// and prefect runs `accio-break <ID> verify`, so boggart never grades itself. A kept break that touches a DoD line gets
// a fix round with boggart-findings.md; one outside the DoD starts none (owl reads it from verdicts.json and logs it).
// After a fix round, a kept repro that only fails to load (a setup error) gets one boggart turn for its imports or
// setup, then verify again; if it still can't load it is logged, not fixed. A boggart or verify step that gives no
// answer never blocks the story: it leaves a note.

const brokenPath = (story) => `.accio/run/${story.id}/boggart-findings.md`
const reproPath = (story, file) => `.accio/run/${story.id}/boggart/repros/${file}`
// `cant_load` is set by breaker.py only when the head runs failed with a setup error. The reason text is never read:
// a break in code the story added says "setup error" for base, and it is a real break.
const cantLoad = (item) => item.verdict === 'kept' && item.cant_load === true
const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`

function tryToBreak(story, pkg) {
  return callRetry(
    `Step 4b, try to break story ${story.id}. Your review package: ${pkg.package}. Follow your checklist: write repros ` +
      `to .accio/run/${story.id}/boggart/repros/ and judge each with \`accio-break ${story.id} try <file>\`. ` +
      'Reply {breaks, questions}.',
    { agentType: BOGGART, model: REVIEW_MODEL, schema: BREAK_SCHEMA, label: label(story, 'boggart') })
}

function verify(story, step, round) {
  return callRetry(
    `Step 4b, verify the breaks of story ${story.id}: run \`accio-break ${story.id} verify\` and reply with its JSON ` +
      '{skipped, repros}, as it prints it, or {error} if it fails. Don\'t judge the repros yourself.',
    { agentType: PREFECT, model: 'haiku', schema: VERIFY_SCHEMA, label: label(story, step, round) })
}

function repairRepros(story, round, stuck) {
  const files = stuck.map((item) => reproPath(story, item.file)).join(', ')
  return callRetry(
    `Step 4b, repair repros of story ${story.id} after fix round ${round}: the fix changed code these repros load, so ` +
      `they fail to load (a setup error): ${files}. Update only their imports or setup so they load again. Never ` +
      'change a repro\'s claim, its source or its expected value, and don\'t run `accio-break`: verify runs next. ' +
      'Reply {breaks, questions}.',
    { agentType: BOGGART, model: REVIEW_MODEL, schema: BREAK_SCHEMA, label: label(story, 'boggart-repair', round) })
}

function writeBrokenFindings(story, round, broken) {
  const data = JSON.stringify(broken.map((item, index) => ({
    id: `boggart-${index + 1}`, where: reproPath(story, item.file), claim: item.claim, dod: item.source, failure: item.reason,
  })))
  return callRetry(
    `Step 4b, write the findings file for fix round ${round} of story ${story.id}: ${brokenPath(story)} ${IN_MAIN}. ` +
      'One item per entry in this list, in the format of the findings template (references/findings-template.md): ' +
      'status open, severity major, confidence 100, and the entry\'s id, where, claim, dod and failure ' +
      `(say in failure that the repro fails twice on head: ${data}). Reply {"done": true} or {error}.`,
    { agentType: PREFECT, model: 'haiku', schema: OUTCOME_SCHEMA, label: label(story, 'boggart-findings', round) })
}

function brokenQuestion(story, broken) {
  const each = broken.map((item) => `its repro: ${reproPath(story, item.file)} (claim: "${item.claim}", from ${item.source})`)
  return `a break boggart found is still there after ${MAX_FIX_ROUNDS} fix rounds; ${each.join('; ')}. ` +
    'Fix it by hand, or change the story?'
}

function boggartNote(kept) {
  const outside = kept.filter((item) => !item.in_dod && !cantLoad(item)).length
  const stuck = kept.filter(cantLoad).length
  return [outside && `boggart: ${plural(outside, 'break')} outside the DoD, logged for owl`,
    stuck && `boggart: ${plural(stuck, 'repro')} can't load, logged for owl`].filter(Boolean).join('; ')
}

const verified = (reply) => !failed(reply) && Array.isArray(reply.repros)

// One fix round for the kept in-DoD breaks: write boggart-findings.md, fix, re-check, then review the fix diff (since
// `head`) as reviewAndFix does, with auror added when it is risky. Returns a stop or {fixes, ruling, head}.
async function fixBreaks(story, worktree, model, used, ruling, broken, head) {
  const wrote = await writeBrokenFindings(story, used + 1, broken)
  if (failed(wrote)) return accioStop(`Writing the boggart findings failed (${(wrote && wrote.error) || 'no answer'}). Try again?`)
  return fixThenReview(story, worktree, model, used + 1, ruling, brokenPath(story), head)
}

// The fix round for a findings file already written, its re-check, and the review of the fix diff since `head`.
async function fixThenReview(story, worktree, model, round, ruling, findingsPath, head) {
  const fixed = await fixRound(story, worktree, round, [findingsPath], tierFor(model, round), ruling)
  if (fixed.stop) return fixed
  const checked = await checkAndFix(story, worktree, model, round, fixed.ruling)
  if (checked.stop) return checked
  const pkg = await packageFor(story, `${checked.fixes}c`, head)
  if (pkg.stop) return pkg
  return reviewLoop(story, worktree, model, checked.ruling, checked.fixes, pkg, panel(story, pkg.risky), checked.fixes)
}

async function boggartStage(story, worktree, model, ruling, fixes, whole, reviewedHead) {
  const off = [!whole.code && 'code', !whole.breaker && 'breaker'].filter(Boolean)
  if (off.length) return { note: `boggart skipped: the ${off.join(' and ')} ${off.length > 1 ? 'flags are' : 'flag is'} false` }  // docs-only, or no `breaker` command
  let pkg = whole
  let head = reviewedHead  // the commit the last review judged: a fix round's diff starts there
  if (fixes > 0) {  // a re-review package holds only a fix diff: boggart reads the whole story
    pkg = await packageFor(story, `${fixes}b`, null)
    if (pkg.stop) return { note: 'boggart did not run: its package failed' }
  }
  const tried = await tryToBreak(story, pkg)
  if (failed(tried)) return { note: 'boggart gave no answer' }
  if (!tried.breaks || !tried.breaks.length) return {}
  let reply = await verify(story, 'verify', 0)
  let used = fixes
  let current = ruling
  let repairedAt = -1  // the fix count a repair turn was used at: one per fix round
  for (;;) {
    if (!verified(reply)) return { fixes: used, ruling: current, head, note: "boggart's verify gave no answer" }
    const kept = reply.repros.filter((item) => item.verdict === 'kept')
    const stuck = kept.filter(cantLoad)
    if (stuck.length && repairedAt !== used) {
      repairedAt = used
      await repairRepros(story, used, stuck)
      reply = await verify(story, 'verify-repair', used)
      continue
    }
    const broken = kept.filter((item) => item.in_dod && !cantLoad(item))
    if (!broken.length) return { fixes: used, ruling: current, head, note: boggartNote(kept) }
    if (used >= MAX_FIX_ROUNDS) return stop(brokenQuestion(story, broken))
    const fixed = await fixBreaks(story, worktree, model, used, current, broken, head)
    if (fixed.stop) return fixed
    used = fixed.fixes
    current = fixed.ruling
    head = fixed.head
    reply = await verify(story, 'verify', used)
  }
}

// --- mad-eye: walks the preview of a story that touches the UI (S-047) ------------------------------------------
// After boggart, a story whose diff touches a `ui_globs` file goes to mad-eye when config.json has a `preview` with
// `"test_data": true` (the user's word that the preview holds test data and test keys; accio can't check it). prefect
// starts the preview, mad-eye walks each visible DoD line and saves a screenshot per line, and prefect stops the
// preview whatever happened. mad-eye never edits, so prefect writes its findings to mad-eye-findings.md, and they go
// to a fix round. A skip, a failure or no answer never blocks the story: it leaves a note for owl.

const SEEN_SCHEMA = {
  type: 'object',
  properties: { findings: { type: 'array', items: { type: 'object' } }, no_browser_tools: { type: 'boolean' }, error: { type: 'string' } },
}
const MISSING_TOOLS = /No such tool available/i  // S-044: what an agent gets for a browser tool the session lacks
const NO_BROWSER = 'the browser tools are missing from this session'
const madEyePath = (story) => `.accio/run/${story.id}/mad-eye-findings.md`
const shotFolder = (story) => `.accio/run/${story.id}/mad-eye/`

function previewStep(story, action) {
  return callRetry(
    `Step 4c, ${action} the preview of story ${story.id}: run \`accio-preview ${story.id} ${action}\`. Reply {"done": true}, ` +
      'or {error} with what it printed if it fails.',
    { agentType: PREFECT, model: 'haiku', schema: OUTCOME_SCHEMA, label: label(story, `preview-${action}`) })
}

function walkPreview(story, pkg) {
  return call(
    `Step 4c, look at the preview of story ${story.id}. Your review package: ${pkg.package}. Follow your instructions: ` +
      'walk each DoD line a user can see, and save one screenshot per line at an absolute path inside the repo: ' +
      `<your working folder>/${shotFolder(story)}<name>.png. You never edit; reply {findings, no_browser_tools}.`,
    { agentType: MAD_EYE, model: REVIEW_MODEL, schema: SEEN_SCHEMA, label: label(story, 'mad-eye') })
}

function writeSeenFindings(story, round, findings) {
  return callRetry(
    `Step 4c, write the findings file for fix round ${round} of story ${story.id}: ${madEyePath(story)} ${IN_MAIN}. One ` +
      'item per entry in this list, in the format of the findings template (references/findings-template.md): status ' +
      "open, severity major, confidence 100, and the entry's id, where, claim, dod and failure (name its screenshot in " +
      `failure): ${JSON.stringify(findings)}. Reply {"done": true} or {error}.`,
    { agentType: PREFECT, model: 'haiku', schema: OUTCOME_SCHEMA, label: label(story, 'mad-eye-findings', round) })
}

// What mad-eye's reply means: {skip: why} when it could not look, {findings} when it saw problems, else {}.
function seenOutcome(reply) {
  if (!reply) return { skip: 'mad-eye gave no answer' }
  if (reply.no_browser_tools) return { skip: NO_BROWSER }
  if (reply.error) return { skip: MISSING_TOOLS.test(reply.error) ? NO_BROWSER : `mad-eye failed (${reply.error})` }
  return Array.isArray(reply.findings) && reply.findings.length ? { findings: reply.findings } : {}
}

// --- mad-eye on a native app: screenshots `ui_evidence` makes (S-068) -------------------------------------------
// With no web `preview`, prefect reads `ui_evidence` (`accio-preview <ID> evidence-plan`). mad-eye writes a steps file
// with Read only, prefect writes it unchanged to ui-steps.txt and runs `accio-preview <ID> evidence --head <head>`,
// which runs the project's command in the worktree, counts the PNGs and stamps the head; then mad-eye judges the
// screenshots with Read only. A command that takes over the screen never runs; every other problem is a skip note.

const PLAN_SCHEMA = {
  type: 'object',
  properties: {
    ui_evidence: { type: 'boolean' }, takes_over_screen: { type: 'boolean' }, steps_doc: { type: 'string' },
    themes: { type: 'array', items: { type: 'string' } }, evidence_files: { type: 'array', items: { type: 'string' } },
    error: { type: 'string' },
  },
  required: ['ui_evidence'],  // a reply without it is retried, never read as false
}
const STEPS_SCHEMA = { type: 'object', properties: { steps: { type: 'string' }, error: { type: 'string' } } }
const EVIDENCE_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' }, skipped: { type: 'boolean' }, reason: { type: 'string' }, folder: { type: 'string' },
    head: { type: 'string' }, screenshots: { type: 'integer' }, error: { type: 'string' },
  },
}
const TAKES_OVER = "ui_evidence.takes_over_screen is true: its command takes over the screen, so it can't run in an unattended build"
const stepsPath = (story) => `.accio/run/${story.id}/ui-steps.txt`
const evidenceFolder = (story) => `.accio/run/${story.id}/ui-evidence/`
const themesText = (plan) => (plan.themes && plan.themes.length
  ? `in every theme the project names (${plan.themes.join(', ')})` : "in the app's default look")

function evidencePlan(story) {
  return callRetry(
    `Step 4c, read the ui_evidence of story ${story.id}: run \`accio-preview ${story.id} evidence-plan\` and reply with ` +
      'its JSON as it prints it, or {error} with what it printed if it fails.',
    { agentType: PREFECT, model: 'haiku', schema: PLAN_SCHEMA, label: label(story, 'evidence-plan') })
}

function askSteps(story, pkg, plan, worktree) {
  return call(
    `Step 4c, evidence mode, pass 1: write the UI steps for story ${story.id}. Your review package: ${pkg.package}. ` +
      `Use only Read. Read the steps vocabulary in ${worktree}/${plan.steps_doc} and write a steps file that shows ` +
      `each DoD line a user can see, ${themesText(plan)}; for anything with a terminal always include resize, ` +
      'minimize and restore, and tab switching. Reply {"steps": "<the file\'s text>"}.',
    { agentType: MAD_EYE, model: REVIEW_MODEL, schema: STEPS_SCHEMA, label: label(story, 'mad-eye-steps') })
}

// 32-bit FNV-1a over the text's code points, as 8 hex digits: the same as preview.steps_sum, so accio-preview refuses
// a ui-steps.txt that prefect changed while copying it (S-070). A copying mistake is the threat, not an attacker.
function stepsSum(text) {
  let value = 0x811c9dc5
  for (const char of text) value = Math.imul(value ^ char.codePointAt(0), 0x01000193) >>> 0
  return value.toString(16).padStart(8, '0')
}

function runEvidence(story, steps, head) {
  return callRetry(
    `Step 4c, make the UI evidence of story ${story.id}. First, with the Write tool, write the value of this JSON ` +
      `string, unchanged and nothing else, to ${stepsPath(story)} ${IN_MAIN}: ${JSON.stringify(steps)}. Then run ` +
      `\`accio-preview ${story.id} evidence --head ${head} --steps-sum ${stepsSum(steps)}\` on its own, with the Bash ` +
      "tool's longest timeout (600000 ms), and reply " +
      'with its JSON as it prints it ({ok, folder, head, screenshots} or {skipped, reason}), or {error} with what it ' +
      'printed if it fails.',
    { agentType: PREFECT, model: 'haiku', schema: EVIDENCE_SCHEMA, label: label(story, 'evidence') })
}

function judgeEvidence(story, pkg, plan) {
  return call(
    `Step 4c, evidence mode, pass 2: judge story ${story.id} from its screenshots. Your review package: ` +
      `${pkg.package}. The evidence folder, made by running your steps on the story's head: <your working folder>/` +
      `${evidenceFolder(story)}. Use only Read: no browser tools. For each DoD line a user can see, look at its ` +
      `screenshots ${themesText(plan)}, and the element dumps there when present, and cite one screenshot per line. ` +
      'A screen that is missing, blank, garbled or wrong is a finding. Reply {findings}, each naming its screenshot.',
    { agentType: MAD_EYE, model: REVIEW_MODEL, schema: SEEN_SCHEMA, label: label(story, 'mad-eye') })
}

// Steps, evidence, judgement. Returns {skip}, {findings} or {}, as walkAndStop does.
async function lookAtEvidence(story, pkg, plan, worktree, head) {
  const asked = await askSteps(story, pkg, plan, worktree)
  if (failed(asked) || typeof asked.steps !== 'string' || !asked.steps.trim()) {
    return { skip: `mad-eye wrote no steps (${(asked && asked.error) || 'no steps file text'})` }
  }
  const ran = await runEvidence(story, asked.steps, head)
  if (failed(ran)) return { skip: `the evidence command did not run (${(ran && ran.error) || 'no answer'})` }
  if (!ran.ok) return { skip: ran.reason || 'the evidence command made no evidence' }
  if (ran.head !== head) return { skip: `the evidence is of commit ${ran.head || 'none'} but the story's head is ${head}, so it is refused` }
  return seenOutcome(await judgeEvidence(story, pkg, plan))
}

// How mad-eye looks at a UI story: {skip: why} or {what, look(pkg, head)}. A web `preview` wins; else `ui_evidence`.
async function lookingWay(story, worktree, whole) {
  if (whole.preview) {
    if (!whole.test_data) return { skip: 'config.json preview has no `"test_data": true`' }
    return { what: 'preview', look: (pkg) => walkAndStop(story, pkg) }
  }
  const plan = await evidencePlan(story)
  if (failed(plan)) return { skip: `reading ui_evidence failed (${(plan && plan.error) || 'no answer'})` }
  if (!plan.ui_evidence) return { skip: 'config.json has no `preview` or `ui_evidence`' }
  if (plan.takes_over_screen) return { skip: TAKES_OVER }
  if (plan.evidence_files && plan.evidence_files.length) {  // S-069: the story's code makes its own evidence
    return { skip: `the story changes how its evidence is made (${plan.evidence_files.join(', ')}); a person should look` }
  }
  return { what: 'screenshots', look: (pkg, head) => lookAtEvidence(story, pkg, plan, worktree, head) }
}

// Preview up, mad-eye, preview down (also when mad-eye fails or throws). Returns {skip}, {findings} or {}.
async function walkAndStop(story, pkg) {
  const started = await previewStep(story, 'start')
  try {
    if (failed(started)) return { skip: `the preview did not start (${(started && started.error) || 'no answer'})` }
    return seenOutcome(await walkPreview(story, pkg))
  } finally {
    await previewStep(story, 'stop')
  }
}

// `state` is {fixes, ruling, head}: where boggart left the story. Returns a stop, or {fixes, ruling, head, note}.
async function madEyeStage(story, worktree, model, state, whole) {
  if (!whole.ui) return state  // the diff touches no `ui_globs` file (or config has none)
  const way = await lookingWay(story, worktree, whole)
  if (way.skip) return { ...state, note: `mad-eye skipped: ${way.skip}` }
  let pkg = whole
  if (state.fixes > 0) {  // a re-review package holds only a fix diff: mad-eye reads the whole story
    pkg = await packageFor(story, `${state.fixes}m`, null)
    if (pkg.stop) return { ...state, note: 'mad-eye did not run: its package failed' }
  }
  const seen = await way.look(pkg, state.head)
  if (seen.skip) return { ...state, note: `mad-eye skipped: ${seen.skip}` }
  if (!seen.findings) return state
  if (state.fixes >= MAX_FIX_ROUNDS) {
    return stop(`mad-eye found problems in the ${way.what} after ${MAX_FIX_ROUNDS} fix rounds: ${JSON.stringify(seen.findings)}. ` +
      'Fix them by hand, or change the story?')
  }
  const round = state.fixes + 1
  const wrote = await writeSeenFindings(story, round, seen.findings)
  if (failed(wrote)) return accioStop(`Writing the mad-eye findings failed (${(wrote && wrote.error) || 'no answer'}). Try again?`)
  const fixed = await fixThenReview(story, worktree, model, round, state.ruling, madEyePath(story), state.head)
  return fixed.stop ? fixed : { fixes: fixed.fixes, ruling: fixed.ruling, head: fixed.head }
}

// --- one story -------------------------------------------------------------------------------------------------

async function runStory(story) {
  const model = story.track === 'feature' ? 'opus' : 'sonnet'
  const blocked = (worktree, ended) => record(story, worktree, 'BLOCKED', ended.question, ended.asked, ended.cause)
  let worktree = story.worktree
  let ruling = ''
  if (story.resume !== 'check') {
    const prepared = await prepare(story)
    if (!prepared || prepared.error || !prepared.brief) {
      const why = (prepared && prepared.error) || 'no answer'
      return record(story, worktree, 'BLOCKED', `Preparing it failed (${why}). Try again?`, false, ACCIO)
    }
    worktree = prepared.worktree
    const built = await build(story, worktree, 0, (ruling) => implement(story, prepared, model, ruling))
    if (built.stop) return blocked(worktree, built)
    ruling = built.ruling
  }
  const checked = await checkAndFix(story, worktree, model, 0, ruling)
  if (checked.stop) return blocked(worktree, checked)
  if (checked.skipped && checked.fixes === 0) return record(story, worktree, 'READY')  // passed review before
  const reviewed = await reviewAndFix(story, worktree, model, checked.ruling, checked.fixes)
  return reviewed.stop ? blocked(worktree, reviewed) : record(story, worktree, 'READY', '', false, CODE, reviewed.note)
}

// --- scheduling ------------------------------------------------------------------------------------------------

function parentState(story, inRun, outcomes) {
  const waiting = story.parents.filter((parent) => inRun.has(parent))
  if (waiting.length > 1) return 'two-parents'
  if (waiting.some((parent) => outcomes.has(parent) && outcomes.get(parent) !== 'READY')) return 'parent-blocked'
  return waiting.every((parent) => outcomes.get(parent) === 'READY') ? 'go' : 'wait'
}

async function schedule(stories, wip) {
  const inRun = new Set(stories.map((story) => story.id))
  const outcomes = new Map()
  const rows = []
  const pending = [...stories]
  const running = new Map()
  while (pending.length || running.size) {
    for (const story of [...pending]) {
      if (running.size >= wip) break
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
    'Reply {"locked": true, "wip": <the "wip" number it printed>, "stories": [...]} with each story\'s id, title, ' +
    'track, parents, resume and worktree. ' +
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
    rows = await schedule(loaded.stories, loaded.wip >= 1 ? loaded.wip : DEFAULT_WIP)
  }
} finally {
  phase('Finish')
  await call('Release the run lock: run `accio-board unlock`. Reply {"done": true} or {error}.',
    { agentType: PORTKEY, model: 'haiku', schema: OUTCOME_SCHEMA, label: 'unlock', phase: 'Finish' })
}
const empty = loaded.error ? `Build didn't start: ${loaded.error}` : 'Nothing to build: no story is ready'
return table(rows, rows.length ? '' : empty)
