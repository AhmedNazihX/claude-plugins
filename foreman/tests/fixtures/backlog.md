# Fixture backlog

## Phase 0

- [x] **F1 · Scaffold** · Deps: – · Type: agent · Solo · Size: S
  Output: `backend/pyproject.toml`. DoD: `uv run pytest` passes.
  **Outcome:** scaffolded.

- [x] **F2 · Database** · Deps: F1 · Type: agent · Resource: db-schema
  Output: migration `001_init.sql`. DoD: tests pass.
  **Outcome:** done.

- [ ] **F3 · Contracts** · Deps: F1 · Type: agent · Size: L
  Output: `backend/app/schemas/result.py`. DoD: round-trip tests pass.

## Phase 1

- [ ] **B1 · Label cases** · Deps: F1 · Type: human
  Output: `eval/cases/labels.yaml`. DoD: the user approved every label.

- [ ] **B2a–c · Case sets, one sub-story per category** · Deps: F3 · Type: mixed
  Output: `eval/cases/<category>/*.yaml`. DoD: approved by the user.
  **Outcome (B2a):** 10 cases.

- [ ] **E1 · Engine node** · Deps: F3, B2a · Type: agent · Lane: Engine
  Output: `backend/app/engine/node.py`. DoD: replay tests on the B2b cases pass.

- [ ] **E2 · Engine node two** · Deps: F3 · Type: agent
  Input: `eval/cases/labels.yaml`. Output: `backend/app/engine/two.py`. DoD: tests pass.

- [ ] **E3 · Store results** · Deps: E2–E2, B2 · Type: agent
  Output: a new migration for the results table. DoD: tests pass.

- [ ] **P1 · Frontend** · Deps: F3 · Type: agent
  Output: `frontend/`. DoD: `pnpm install --frozen-lockfile && pnpm build` pass.

- [ ] **W1 · Week-nine check** · Deps: – (run in week 9) · Type: agent
  Output: `docs/decisions/007-freshness.md`. DoD: recorded.
