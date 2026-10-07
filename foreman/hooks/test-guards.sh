#!/bin/bash
# Regression tests for the foreman guard hooks (gate.sh, lane-guard.sh, worker-guard.sh).
# Run: bash hooks/test-guards.sh   (from the plugin root)
# Builds a throwaway repo with its own config, backlog and a real agent-style worktree; never touches your repo.

SRC="$(cd "$(dirname "$0")" && pwd)"
BACKLOG_PY="$SRC/../scripts/backlog.py"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
FAILS=0

R="$TMP/repo"
mkdir -p "$R/.claude/hooks/lib" "$R/.claude/scripts" "$R/docs" "$R/src/app/eval" "$R/eval"
cp "$SRC/gate.sh" "$SRC/lane-guard.sh" "$R/.claude/hooks/"
cp "$SRC/lib/strip-heredocs.awk" "$R/.claude/hooks/lib/"
cp "$BACKLOG_PY" "$R/.claude/scripts/backlog.py"
cat > "$R/.claude/foreman.json" <<'JSON'
{
  "lanes":   {"Corpus": {"deny": ["eval"], "allow": []}},
  "stories": {"C2": {"deny": ["eval"], "allow": ["eval/split.json"]}},
  "gates":   [{"path": "src/app/engine", "requires": "eval/split.json", "reason": "test gate"}]
}
JSON
cat > "$R/docs/BACKLOG.md" <<'MD'
- [ ] **C1 · Parser** · Deps: – · Type: agent · Lane: Corpus
  Output: x. DoD: y.
- [ ] **C2 · Guidelines** · Deps: – · Type: agent · Lane: Corpus
  Output: x. DoD: y.
- [ ] **B4 · Cases** · Deps: – · Type: mixed · Lane: Benchmark
  Output: x. DoD: y.
MD
echo '{}' > "$R/eval/cases.json"
git -C "$R" init -q && git -C "$R" add -A && git -C "$R" commit -q -m init
# The plugin reads the project config via CLAUDE_PROJECT_DIR and its helper via CLAUDE_PLUGIN_ROOT.
export CLAUDE_PROJECT_DIR="$R" CLAUDE_PLUGIN_ROOT="$SRC/.."

GATE="$R/.claude/hooks/gate.sh"
GUARD="$R/.claude/hooks/lane-guard.sh"
E=src/app/engine     # built at runtime so this file's commands never mention the gated path

run() {  # run <hook> <expected exit> <json> <label>
  printf '%s' "$3" | "$1" >/dev/null 2>&1
  local c=$?
  if [ "$c" = "$2" ]; then echo "  ok    $4"; else echo "  FAIL  $4 (exit $c, want $2)"; FAILS=$((FAILS + 1)); fi
}
bash_in() { jq -nc --arg c "$2" --arg d "$1" '{tool_name:"Bash",cwd:$d,tool_input:{command:$c}}'; }
file_in() { jq -nc --arg t "$1" --arg d "$2" --arg p "$3" '{tool_name:$t,cwd:$d,tool_input:{file_path:$p,content:"x"}}'; }

echo "gate, before eval/split.json is committed"
BRACE='mkdir -p src/app/{models,engine}'   # bash 3.2 brace-expands literals inside "$(...)"
run "$GATE" 2 "$(file_in Write "$R" "$R/$E/graph.py")"                 "Write under the gated path"
run "$GATE" 2 "$(bash_in "$R" "mkdir -p $E")"                           "mkdir the gated path"
run "$GATE" 2 "$(bash_in "$R" "$BRACE")"                                "mkdir with brace expansion"
run "$GATE" 2 "$(bash_in "$R" "cd src/app && mkdir engine")"            "cd parent, mkdir leaf"
run "$GATE" 2 "$(bash_in "$R" $'cat > '$E$'/a.py <<EOF\nx\nEOF')"       "heredoc into the gated path"
run "$GATE" 0 "$(bash_in "$R" $'cat > notes.md <<\'EOF\'\n'$E$'\nEOF')" "heredoc only mentioning it"
run "$GATE" 0 "$(bash_in "$R" "ls $E 2>/dev/null")"                     "ls with 2>/dev/null"
run "$GATE" 0 "$(file_in Write "$R" "$R/src/app/models.py")"            "Write elsewhere"
run "$GATE" 2 "$(bash_in "$R" "sed -i '' s/a/b/ $E/graph.py")"           "sed -i on the gated path"
run "$GATE" 2 "$(bash_in "$R" "python3 -c \"open('$E/x.py','w')\"")"     "python open(…, 'w') on the gated path"
run "$GATE" 2 "$(bash_in "$R" "git checkout other -- $E")"               "git checkout -- the gated path"
run "$GATE" 0 "$(bash_in "$R" "grep -rn x $E")"                          "reading the gated path"
echo '{}' > "$R/eval/split.json"; git -C "$R" add eval/split.json; git -C "$R" commit -q -m split
echo "gate, after the split is committed"
run "$GATE" 0 "$(file_in Write "$R" "$R/$E/graph.py")"                 "Write under the gated path"

# A real worktree, like an agent's, on a Corpus-lane story branch.
W="$R/.claude/worktrees/w1"
git -C "$R" worktree add -q -b story/C1-parser "$W" 2>/dev/null
echo "lane guard in a worktree on story/C1 (lane Corpus, deny eval)"
run "$GUARD" 2 "$(file_in Read "$W" "$R/eval/cases.json")"               "Read main checkout's eval (absolute)"
run "$GUARD" 2 "$(file_in Read "$W" "$W/eval/cases.json")"               "Read worktree's eval (absolute)"
run "$GUARD" 2 "$(file_in Read "$W" "eval/split.json")"                  "Read eval (relative)"
run "$GUARD" 0 "$(file_in Read "$W" "$W/src/app/eval/__init__.py")"      "Read a package that is also named eval"
run "$GUARD" 2 "$(jq -nc --arg d "$W" --arg p "$R/eval" '{tool_name:"Grep",cwd:$d,tool_input:{pattern:"x",path:$p}}')" "Grep in eval"
run "$GUARD" 2 "$(jq -nc --arg d "$W" '{tool_name:"Glob",cwd:$d,tool_input:{pattern:"**/eval/**"}}')" "Glob **/eval/**"
run "$GUARD" 2 "$(bash_in "$W" "cat eval/cases.json")"                   "cat eval/…"
run "$GUARD" 2 "$(bash_in "$W" "ls $R/eval")"                            "ls main checkout's eval"
run "$GUARD" 2 "$(bash_in "$W" "grep -rn x eval")"                       "grep -rn x eval"
run "$GUARD" 2 "$(bash_in "$W" "git show main:eval/cases.json")"         "git show main:eval/…"
run "$GUARD" 2 "$(bash_in "$W" "git checkout main -- eval")"             "git checkout main -- eval"
run "$GUARD" 2 "$(bash_in "$W" "git sparse-checkout set --no-cone '/*'")" "widen the sparse checkout"
run "$GUARD" 0 "$(bash_in "$W" "git sparse-checkout list")"              "sparse-checkout list"
run "$GUARD" 0 "$(bash_in "$W" "cat src/app/eval/__init__.py")"          "cat the eval package"
run "$GUARD" 0 "$(bash_in "$W" 'git commit -m "feat: never read eval"')" "commit message mentioning eval"
run "$GUARD" 0 "$(bash_in "$W" $'cat > n.md <<\'EOF\'\neval/x\nEOF')"   "heredoc mentioning eval"
# Found in the 2026-09-30 review: other checkouts of the repo aren't sparse.
S="$TMP/scratch"
git -C "$R" worktree add -q --detach "$S" 2>/dev/null
run "$GUARD" 2 "$(jq -nc --arg d "$W" --arg p "$R" '{tool_name:"Grep",cwd:$d,tool_input:{pattern:"x",path:$p}}')" "Grep over the main checkout's root"
run "$GUARD" 2 "$(file_in Read "$W" "$S/eval/cases.json")"               "Read eval in a scratch worktree"
run "$GUARD" 2 "$(bash_in "$W" "grep -rn x $R")"                          "grep -rn over the main checkout"
run "$GUARD" 2 "$(bash_in "$W" "cat $S/eval/cases.json")"                 "cat eval in a scratch worktree"
run "$GUARD" 0 "$(jq -nc --arg d "$W" --arg p "$W" '{tool_name:"Grep",cwd:$d,tool_input:{pattern:"x",path:$p}}')" "Grep over its own worktree"
run "$GUARD" 0 "$(bash_in "$W" 'eval "$(ssh-agent -s)"')"                "the shell's eval builtin"
run "$GUARD" 0 "$(bash_in "$W" "uv run pytest -k eval")"                  "pytest -k eval (an option value)"
run "$GUARD" 2 "$(bash_in "$W" "ls eval")"                                "ls eval (a bare folder name)"
git -C "$R" worktree remove "$S" 2>/dev/null

git -C "$W" checkout -q -b story/C2-guidelines
echo "lane guard on story/C2 (story rule: allow eval/split.json)"
run "$GUARD" 0 "$(file_in Read "$W" "$R/eval/split.json")"               "Read the allowed file"
run "$GUARD" 0 "$(bash_in "$W" "jq .pile_b eval/split.json")"            "jq the allowed file"
run "$GUARD" 0 "$(bash_in "$W" "python3 -c \"open('eval/split.json')\"")" "python opens the allowed file"
run "$GUARD" 2 "$(file_in Read "$W" "$R/eval/cases.json")"               "Read another eval file"
run "$GUARD" 2 "$(bash_in "$W" "cat eval/cases.json")"                   "cat another eval file"

git -C "$W" checkout -q -b story/B4-cases
echo "lane guard on story/B4 (lane Benchmark, no rule) and on main"
run "$GUARD" 0 "$(file_in Read "$W" "$R/eval/cases.json")"               "B4 reads eval"
run "$GUARD" 0 "$(file_in Read "$R" "$R/eval/cases.json")"               "main reads eval"

WG="$SRC/worker-guard.sh"
# The worker guard applies to subagents: their hook input carries agent_id, the main thread's doesn't.
bash_in() { jq -nc --arg c "$2" --arg d "$1" '{tool_name:"Bash",cwd:$d,agent_id:"a1",tool_input:{command:$c}}'; }
file_in() { jq -nc --arg t "$1" --arg d "$2" --arg p "$3" '{tool_name:$t,cwd:$d,agent_id:"a1",tool_input:{file_path:$p,content:"x"}}'; }
echo "worker guard on story/B4 (base branch main)"
run "$WG" 2 "$(bash_in "$W" "git push origin story/B4-cases")"            "a worker pushes"
run "$WG" 2 "$(bash_in "$W" "git rebase main")"                           "a worker rebases"
run "$WG" 2 "$(bash_in "$W" "git merge story/C1-parser")"                 "a worker merges another story"
run "$WG" 0 "$(bash_in "$W" "git merge main")"                            "a worker merges the base branch (conflicts)"
run "$WG" 0 "$(bash_in "$W" "git merge --abort")"                         "a worker aborts a merge"
run "$WG" 2 "$(bash_in "$W" "git switch main")"                           "a worker switches to main"
run "$WG" 2 "$(bash_in "$W" "git checkout -b other")"                     "a worker starts another branch"
run "$WG" 0 "$(bash_in "$W" "git checkout -- src/app/models.py")"         "a worker restores one file"
run "$WG" 2 "$(file_in Edit "$W" "$W/docs/BACKLOG.md")"                   "a worker edits the backlog"
run "$WG" 2 "$(bash_in "$W" "python3 backlog.py tick B4 done")"           "a worker ticks the backlog"
run "$WG" 2 "$(bash_in "$W" "echo x >> docs/BACKLOG.md")"                 "a worker appends to the backlog"
run "$WG" 0 "$(bash_in "$W" "python3 backlog.py show B4")"                "a worker reads its story"
run "$WG" 0 "$(bash_in "$W" "git commit -m 'feat: cases'")"               "a worker commits"
run "$WG" 0 "$(bash_in "$R" "git push origin main")"                      "the orchestrator on main pushes"
run "$WG" 0 "$(file_in Edit "$R" "$R/docs/BACKLOG.md")"                   "the orchestrator edits the backlog"
# Found in the 0.3.0 review.
SHA=$(git -C "$R" rev-parse HEAD)
run "$WG" 2 "$(bash_in "$W" "git checkout $SHA")"                         "a worker checks out a commit (detaches)"
run "$WG" 2 "$(bash_in "$W" "git checkout HEAD~1")"                       "a worker checks out HEAD~1"
run "$WG" 2 "$(bash_in "$W" "git switch --create foo")"                   "a worker creates a branch with switch --create"
run "$WG" 2 "$(bash_in "$W" "git pull --rebase origin main")"             "a worker pulls with rebase"
run "$WG" 2 "$(bash_in "$W" "git pull origin other")"                     "a worker pulls another branch"
run "$WG" 0 "$(bash_in "$W" "git pull origin main")"                      "a worker pulls the base branch"
run "$WG" 2 "$(bash_in "$W" "git branch -f main HEAD")"                   "a worker moves main with branch -f"
run "$WG" 2 "$(bash_in "$W" "git update-ref refs/heads/main HEAD")"       "a worker runs update-ref"
run "$WG" 0 "$(bash_in "$W" 'git merge -m "Merge main" main')"           "merge -m <msg> main passes"
run "$WG" 0 "$(bash_in "$W" "git merge -X theirs main")"                  "merge -X theirs main passes"
run "$WG" 0 "$(bash_in "$W" "git merge --no-edit origin/main")"           "merge --no-edit origin/main passes"
run "$WG" 0 "$(bash_in "$W" "grep -in B4 docs/BACKLOG.md")"               "grep -i reads the backlog"
run "$WG" 0 "$(bash_in "$W" 'git commit -m "fix: x; git push later"')"   "a commit message mentioning git push"
run "$WG" 0 "$(bash_in "$W" 'echo "remember: backlog.py tick B4"')"      "echo mentioning backlog.py tick"
run "$WG" 2 "$(file_in Edit "$W" "$W/docs/backlog.md")"                   "editing docs/backlog.md (case-insensitive)"
run "$WG" 2 "$(bash_in "$W" "sed -i '' s/x/y/ docs/BACKLOG.md")"          "sed -i on the backlog"
SCR="$TMP/auditor-scratch"
git -C "$R" worktree add -q --detach "$SCR" 2>/dev/null
run "$WG" 0 "$(bash_in "$W" "git -C $SCR checkout --detach HEAD")"       "the test auditor detaches its own scratch copy"
run "$WG" 2 "$(bash_in "$W" "git -C $R push origin main")"               "git -C <main checkout> push is still blocked"
git -C "$R" worktree remove "$SCR" 2>/dev/null
git -C "$W" checkout -q --detach 2>/dev/null
run "$WG" 2 "$(bash_in "$W" "git push origin HEAD:main")"                 "a detached worktree still can't push"
run "$WG" 2 "$(file_in Edit "$W" "$W/docs/BACKLOG.md")"                   "a detached worktree still can't edit the backlog"
git -C "$W" checkout -q story/B4-cases 2>/dev/null
# Continue a story (0.7.0): a relaunched worker's fresh worktree switches onto the existing story branch, once.
FRESH="$R/.claude/worktrees/agent-fresh"
git -C "$R" worktree add -q -b worktree-agent-fresh "$FRESH" 2>/dev/null
run "$WG" 0 "$(bash_in "$FRESH" "git switch story/C2-guidelines")"        "a fresh worker switches onto a story branch"
run "$WG" 2 "$(bash_in "$FRESH" "git checkout story/C2-guidelines")"      "…but not with checkout"
run "$WG" 2 "$(bash_in "$FRESH" "git switch main")"                       "a fresh worker can't switch to main"
run "$WG" 2 "$(bash_in "$FRESH" "git switch -c story/C2-guidelines-2")"   "a fresh worker can't create a story branch"
run "$WG" 2 "$(bash_in "$W" "git switch story/C2-guidelines")"            "a worker on a story branch can't switch stories"
# Found in the 0.7.0 review.
run "$WG" 2 "$(bash_in "$FRESH" "git -C $W switch story/C2-guidelines")"  "a fresh worker can't switch another worktree with -C"
run "$WG" 2 "$(bash_in "$FRESH" "git switch story/C2-guidelines && git switch story/C1-parser")" \
  "a fresh worker can't chain two switches"
git -C "$R" worktree remove "$FRESH" 2>/dev/null
# Found in the 0.3.4 trial: the orchestrator's shell was still in a worktree after `cd <worktree> && uv run pytest`.
MERGE="git merge --no-ff story/B4-cases -m 'merge: story B4'"
run "$WG" 0 "$(jq -nc --arg c "cd $R && $MERGE" --arg d "$W" '{tool_name:"Bash",cwd:$d,tool_input:{command:$c}}')" \
  "the orchestrator merges from a shell left in a worktree"
run "$WG" 2 "$(bash_in "$W" "cd $R && $MERGE")"                           "a worker can't merge by cd-ing to the main checkout"

echo
[ "$FAILS" = 0 ] && echo "All guard tests passed." || { echo "$FAILS guard test(s) failed."; exit 1; }
