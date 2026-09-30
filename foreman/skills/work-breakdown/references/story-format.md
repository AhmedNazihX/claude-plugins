# Story format

Each story is one list item. The header line carries the machine-readable fields. The indented lines carry what a
fresh session needs. `scripts/backlog.py` parses exactly this shape.

```markdown
- [ ] **C1 · CSV importer** · Deps: B1 · Type: agent · Lane: Corpus · Size: M
  Context: Design › Import, Data rules. Input: `data/raw/*.csv`. Output: `backend/app/importer/csv.py` →
  `data/parsed/<source>.jsonl`, one record per row, with stable IDs derived from the source key.
  DoD: tests against 5 named rows pass, including one with a malformed date; ruff, pyright and pytest pass.
```

## Header fields

| Field | Required | Meaning |
| --- | --- | --- |
| `ID · Title` | yes | ID = 1–3 capital letters (usually the phase: F, B, C, E, P) + a number + an optional suffix (`P2a`). Grouped siblings: `B5a–e`. The title is a short noun phrase. |
| `Deps:` | yes | Comma-separated IDs, ranges (`E2–E7`), a group (`B5`), `–` for none. Plain text for manual conditions: `– (run in week 9)`, `F4 (after a few sessions)`. |
| `Type:` | yes | `agent`: an agent can finish it alone. `mixed`: an agent drafts, the user reviews or approves. `human`: the user does it, and an agent may help with formats. |
| `Lane:` | no | A group of stories that share context or rules (Infra, Corpus, Benchmark, Product). Used for parallel planning and scoped rules. |
| `Size:` | no | S, M (default) or L. Weights the critical path. An L story should be rare; split it if you can. |
| `Solo` | no | The story runs with nothing else in flight. Use it for the scaffold that every worktree branches from, or a serial chain. |
| `Resource:` | no | A shared thing the story changes: `db-schema`, `lockfile`, `api-client`, `budget`. At most one story per resource per wave. |

## Body lines

- **Context:** the exact design-doc sections to read (`Design › Evaluation › Metrics`). No section, no story.
- **Input:** the exact files, datasets or outputs of earlier stories it consumes.
- **Output:** the exact files or paths it creates or changes, with the key contents named (fields, tables, endpoints).
  Write full paths, from the repo root or from the package root named in `docs/LAYOUT.md`. Each path must fit the
  layout: `nodes/scope.py` is ambiguous, `backend/app/engine/nodes/scope.py` isn't.
- **DoD:** checkable claims only. A command that passes, a named test, a count, a file that exists with named
  contents, or "the user has approved X". Always include the project's standard checks (lint, types, tests).

After a story is merged, `backlog.py tick <ID> "<note>"` ticks it and adds an `**Outcome:**` line.

## Atomicity: split when…

- The DoD joins two subsystems with "and": "the parser **and** the loader **and** the embeddings" becomes three stories.
- It needs both an agent and the user at different points. Split it into the agent part and the approval part, or make it `mixed` with the approval as the last DoD line.
- It's longer than about one focused session. Or its Output lists more than 5–6 unrelated files.
- Part of it could start earlier than the rest. The earlier part becomes its own story, so it can join an earlier wave.

## Good and bad

| Bad | Why | Good |
| --- | --- | --- |
| "Set up the backend" | Not checkable; no output named | "Backend scaffold: `backend/pyproject.toml` (uv), package `app/` with empty subpackages X, Y, Z, `.env.example` … DoD: `uv sync && uv run pytest && uv run ruff check` pass with one trivial test" |
| "DoD: retrieval works well" | Not checkable | "DoD: the query 'estimates whether a tenant will pay rent' returns Annex III 5(b) in the top 5; the German query test passes; the exclude filter test passes" |
| "Deps: after the database is ready" | Not an ID, so the graph can't use it | "Deps: F4" |
| One story "Write all test cases" | Weeks of work, and needs human approval throughout | `B5a–e`, one sub-story per category, each `mixed`, DoD "the user approved each file" |
| `Type: agent` on labelling data | The agent can't approve its own labels | `Type: mixed`: the agent drafts, the user approves |
| Hand-drawn critical path in prose | Drifts as deps change | Paste the output of `backlog.py graph` and `plan` |
| "Output: `eval/split.py`" in a folder of test data | Code inside a data folder that a lane must never read; outside the lint and type setup | "Output: `backend/app/eval/split.py` (`app eval split`), which writes `eval/split.json`", as `docs/LAYOUT.md` places it |

## Gates

A **gate** is a story that others must wait for, because the design says so. Example: "commit the test split before
any engine code exists". Mark it clearly in its title (`(gate)`) and in the DoD (what must be committed, and how to
check it). If the gate can be enforced mechanically (a file that must exist before a path is written, or a folder
some lanes must never read), note it for the `setup` and `guardrails` skills, which can install a hook for it.
