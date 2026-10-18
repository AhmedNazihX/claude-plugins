# 007 — Name: `accio`, with a wizarding-school map

Date: 2026-10-17 · Status: decided by the user

## Decision
- **Plugin id:** `accio`. The state folder is `.accio/`. It is published to the user's `nazihx` marketplace
  (`~/Workspace/claude-plugins-release`).
- **The build skill is `brew` (potion brewing), not `accio`,** so the command is not `/accio:accio`. This is
  Claude's naming call, and the user may override it.
- **Rule: magic names, plain words.** Every description and every report says in plain English what is happening.
  *Added 2026-10-19 (the user's request):* every agent's and skill's description starts with its plain role ("The
  builder (house-elf): …", "Review (owl): …"), a guard's block message names its role, and a build question names
  an agent with its role; the README has a role table.
  Board columns keep plain names. Spell words and lore terms are used; character names and "Hogwarts" branding are
  not.

### Skills
| Phase | Skill | Does |
|---|---|---|
| 1 Design | `wand` | stack and architecture: interview, research, 2–3 options, grilling, `.accio/design.md` |
| 2 Planning | `sort` | design → story files, deps, tracks, checkable DoDs |
| 3 Iteration planning | `prophecy` | pick ≤ 8 stories, sharpen DoDs, grill, one "go" |
| 4 Build | `brew` | starts the build workflow on the ready stories |
| 5 Review & QA | `owl` | demo notes, accept/reject, questions, merge and push in one batch |
| 6 Retro (v2) | `pensieve` | cost, flow, repeated findings → proposed rules |
| any | `map` | the board |
| any | `reparo` | quick fix outside an iteration |
| any | `lumos` | explain anything more simply |
| any | `vow` | record a decision |

### Agents
| Agent | Role | Model |
|---|---|---|
| `seeker` | researcher | Sonnet |
| `wandmaker` | architect | Opus |
| `portkey` | worktree + brief | Haiku |
| `house-elf` | implementer | Sonnet / Opus |
| `prefect` | checks (skips anything already passed) | Haiku |
| `examiner` | spec reviewer, and backlog checker in `sort` | Sonnet |
| `professor` | quality reviewer | Sonnet |
| `auror` | security reviewer | Sonnet |
| `headmaster` | judge | Sonnet |
| `librarian` | doc lookups | Haiku |
| `howler` | CI watcher after `owl`'s push (v2, S-029; named 2026-10-19) | Haiku |

### Hooks
- `protego`: destructive commands
- `fidelius`: secrets

## Names considered
- marauder, patronus, mischief, diagon, quill, wizardry, castle, spellcraft, spellbook.
- hogwarts was rejected over the trademark.
- Names the user found hard to say or write were replaced: veritaserum → prophecy, wizengamot → headmaster,
  sneakoscope → prefect.
