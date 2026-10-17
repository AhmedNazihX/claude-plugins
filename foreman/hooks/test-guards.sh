#!/bin/bash
# Regression tests for the foreman guard hooks (gate.sh, lane-guard.sh, worker-guard.sh).
# Run: bash hooks/test-guards.sh   (from the plugin root)
# Builds a throwaway repo with its own config, backlog and a real agent-style worktree; never touches your repo.

SRC="$(cd "$(dirname "$0")" && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
FAILS=0

R="$TMP/repo"
mkdir -p "$R/.claude/hooks/lib" "$R/docs" "$R/src/app/eval" "$R/eval"
cp "$SRC/gate.sh" "$SRC/lane-guard.sh" "$R/.claude/hooks/"
cp "$SRC/lib/strip-heredocs.awk" "$R/.claude/hooks/lib/"
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
msg() {  # msg <hook> <json> <alternative> <label>: blocks, and the message ends by naming the way through
  local out c
  out=$(printf '%s' "$2" | "$1" 2>&1 >/dev/null)
  c=$?
  if [ "$c" = 2 ] && printf '%s' "$out" | grep -qF -- "$3"; then echo "  ok    $4"
  else echo "  FAIL  $4 (exit $c, want 2 and '$3' in: $out)"; FAILS=$((FAILS + 1)); fi
}
# A PATH holding only the tools the hooks use, without the one named in $1 (to test what happens when it's missing).
path_without() {
  local dir="$TMP/bin-without-$1" tool p
  mkdir -p "$dir"
  for tool in git jq python3 sed awk grep tr cat dirname basename wc mktemp; do
    [ "$tool" = "$1" ] && continue
    p=$(command -v "$tool" 2>/dev/null) && ln -sf "$p" "$dir/$tool"
  done
  echo "$dir"
}
# Subagent input (agent_id set): the lane guard applies only to subagents; the gate applies to every session.
bash_in() { jq -nc --arg c "$2" --arg d "$1" '{tool_name:"Bash",cwd:$d,agent_id:"a1",tool_input:{command:$c}}'; }
file_in() { jq -nc --arg t "$1" --arg d "$2" --arg p "$3" '{tool_name:$t,cwd:$d,agent_id:"a1",tool_input:{file_path:$p,content:"x"}}'; }

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
echo "gate, block messages name the way through"
msg "$GATE" "$(file_in Write "$R" "$R/$E/graph.py")" "Commit 'eval/split.json' first" "Write: commit <requires> first"
msg "$GATE" "$(bash_in "$R" "mkdir -p $E")"           "Commit 'eval/split.json' first" "shell: commit <requires> first"
NOJQ=$(path_without jq)
PATH="$NOJQ" msg "$GATE" "$(file_in Write "$R" "$R/$E/graph.py")" "brew install jq" "without jq: install it"
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
run "$GUARD" 2 "$(jq -nc --arg d "$W" --arg p "$R/eval" '{tool_name:"Grep",cwd:$d,agent_id:"a1",tool_input:{pattern:"x",path:$p}}')" "Grep in eval"
run "$GUARD" 2 "$(jq -nc --arg d "$W" '{tool_name:"Glob",cwd:$d,agent_id:"a1",tool_input:{pattern:"**/eval/**"}}')" "Glob **/eval/**"
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
run "$GUARD" 2 "$(jq -nc --arg d "$W" --arg p "$R" '{tool_name:"Grep",cwd:$d,agent_id:"a1",tool_input:{pattern:"x",path:$p}}')" "Grep over the main checkout's root"
run "$GUARD" 2 "$(file_in Read "$W" "$S/eval/cases.json")"               "Read eval in a scratch worktree"
run "$GUARD" 2 "$(bash_in "$W" "grep -rn x $R")"                          "grep -rn over the main checkout"
run "$GUARD" 2 "$(bash_in "$W" "cat $S/eval/cases.json")"                 "cat eval in a scratch worktree"
run "$GUARD" 0 "$(jq -nc --arg d "$W" --arg p "$W" '{tool_name:"Grep",cwd:$d,agent_id:"a1",tool_input:{pattern:"x",path:$p}}')" "Grep over its own worktree"
run "$GUARD" 0 "$(bash_in "$W" 'eval "$(ssh-agent -s)"')"                "the shell's eval builtin"
run "$GUARD" 0 "$(bash_in "$W" "uv run pytest -k eval")"                  "pytest -k eval (an option value)"
run "$GUARD" 2 "$(bash_in "$W" "ls eval")"                                "ls eval (a bare folder name)"
# 2026-10-13: the orchestrator's shell, left inside this worktree, was treated as story C1's worker and locked out
# of the main checkout. The main thread's input has no agent_id, so the guard lets it through.
main_bash() { jq -nc --arg c "$2" --arg d "$1" '{tool_name:"Bash",cwd:$d,tool_input:{command:$c}}'; }
run "$GUARD" 0 "$(main_bash "$W" "cd $R && git status")"                  "the main thread in the worktree reaches main"
run "$GUARD" 0 "$(main_bash "$W" "cat $R/eval/cases.json")"               "the main thread in the worktree reads main's eval"
run "$GUARD" 2 "$(bash_in "$W" "cd $R && git status")"                    "a worker in the worktree can't reach main"
echo "lane guard, block messages name the config key and the story exception"
LANE_KEY="lanes.Corpus.deny"
EXC="stories.C1.allow"
msg "$GUARD" "$(file_in Read "$W" "$W/eval/cases.json")" "$EXC" "Read: names the story exception"
msg "$GUARD" "$(file_in Read "$W" "$W/eval/cases.json")" "$LANE_KEY" "Read: names the lane's config key"
msg "$GUARD" "$(jq -nc --arg d "$W" --arg p "$R/eval" '{tool_name:"Grep",cwd:$d,agent_id:"a1",tool_input:{pattern:"x",path:$p}}')" \
  "$EXC" "Grep path: names the story exception"
msg "$GUARD" "$(jq -nc --arg d "$W" '{tool_name:"Glob",cwd:$d,agent_id:"a1",tool_input:{pattern:"**/eval/**"}}')" \
  "$EXC" "Glob pattern: names the story exception"
msg "$GUARD" "$(bash_in "$W" "cat eval/cases.json")"                     "$EXC" "shell touches a denied folder"
msg "$GUARD" "$(bash_in "$W" "grep -rn x $R")"                           "$EXC" "shell reaches another checkout"
msg "$GUARD" "$(bash_in "$W" "git sparse-checkout set --no-cone '/*'")"  "$EXC" "shell widens the sparse checkout"
PATH="$NOJQ" msg "$GUARD" "$(file_in Read "$W" "$W/eval/cases.json")"    "brew install jq" "without jq: install it"
PATH="$(path_without python3)" msg "$GUARD" "$(file_in Read "$W" "$W/eval/cases.json")" \
  "stories.C1 (with the deny list next to it)" "without python3: ask the user for python3 or a full story rule"
# Found in Q11 (fixed in Q10): a backlog.py that fails to run used to switch the lane checks off.
BROKEN="$TMP/broken-plugin"
mkdir -p "$BROKEN/scripts" "$TMP/no-lanes/.claude"
echo 'import backlog_model_missing' > "$BROKEN/scripts/backlog.py"
echo '{"lanes": {}}' > "$TMP/no-lanes/.claude/foreman.json"
CLAUDE_PLUGIN_ROOT="$BROKEN" msg "$GUARD" "$(file_in Read "$W" "$W/eval/cases.json")" \
  "stories.C1 (with the deny list next to it)" "a failing backlog.py blocks: ask the user"
CLAUDE_PLUGIN_ROOT="$BROKEN" run "$GUARD" 2 "$(file_in Read "$W" "$W/src/app/models.py")" \
  "a failing backlog.py blocks even outside the denied folder"
CLAUDE_PLUGIN_ROOT="$BROKEN" CLAUDE_PROJECT_DIR="$TMP/no-lanes" run "$GUARD" 0 \
  "$(file_in Read "$W" "$W/eval/cases.json")" "near-miss: a failing backlog.py with no lane deny lists passes"
# Q10 review: lanes whose deny lists are empty or missing have nothing to enforce.
echo '{"lanes": {"a": {"deny": []}, "b": {"allow": ["x"]}}}' > "$TMP/no-lanes/.claude/foreman.json"
CLAUDE_PLUGIN_ROOT="$BROKEN" CLAUDE_PROJECT_DIR="$TMP/no-lanes" run "$GUARD" 0 \
  "$(file_in Read "$W" "$W/eval/cases.json")" "near-miss: a failing backlog.py with empty or allow-only lanes passes"
# Q10 review: a warning on stderr from a working backlog.py must not turn the lanes off.
WARN="$TMP/warn-plugin"
mkdir -p "$WARN/scripts"
printf 'import os, sys\nprint("a warning", file=sys.stderr, flush=True)\nreal = %s\nos.execv(sys.executable, [sys.executable, real] + sys.argv[1:])\n' \
  "'$SRC/../scripts/backlog.py'" > "$WARN/scripts/backlog.py"
CLAUDE_PLUGIN_ROOT="$WARN" msg "$GUARD" "$(file_in Read "$W" "$W/eval/cases.json")" "$LANE_KEY" \
  "a backlog.py warning on stderr keeps the lane check on"
CLAUDE_PLUGIN_ROOT="$WARN" run "$GUARD" 0 "$(file_in Read "$W" "$W/src/app/models.py")" \
  "near-miss: with the warning, a file outside the denied folder passes"
git -C "$R" worktree remove "$S" 2>/dev/null

git -C "$W" checkout -q -b story/C2-guidelines
echo "lane guard on story/C2 (story rule: allow eval/split.json)"
run "$GUARD" 0 "$(file_in Read "$W" "$R/eval/split.json")"               "Read the allowed file"
run "$GUARD" 0 "$(bash_in "$W" "jq .pile_b eval/split.json")"            "jq the allowed file"
run "$GUARD" 0 "$(bash_in "$W" "python3 -c \"open('eval/split.json')\"")" "python opens the allowed file"
run "$GUARD" 2 "$(file_in Read "$W" "$R/eval/cases.json")"               "Read another eval file"
run "$GUARD" 2 "$(bash_in "$W" "cat eval/cases.json")"                   "cat another eval file"
msg "$GUARD" "$(file_in Read "$W" "$R/eval/cases.json")" "stories.C2.deny" "a story's own rule names its config key"

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
echo "worker guard, block messages name the way through"
FOLLOW="Put it under Follow-ups in your report; the orchestrator updates the backlog."
REPORT="Report it in your final message; the orchestrator does it."
msg "$WG" "$(file_in Edit "$W" "$W/docs/BACKLOG.md")"                "$FOLLOW" "edit the backlog: Follow-ups"
msg "$WG" "$(bash_in "$W" "python3 backlog.py tick B4 done")"        "$FOLLOW" "backlog.py tick: Follow-ups"
msg "$WG" "$(bash_in "$W" "echo x >> docs/BACKLOG.md")"              "$FOLLOW" "shell write to the backlog: Follow-ups"
msg "$WG" "$(bash_in "$W" "git push origin story/B4-cases")"         "$REPORT" "push: report it"
msg "$WG" "$(bash_in "$W" "git rebase main")"                        "$REPORT" "rebase: report it"
msg "$WG" "$(bash_in "$W" "git merge story/C1-parser")"              "$REPORT" "merge another story: report it"
msg "$WG" "$(bash_in "$W" "git update-ref refs/heads/main HEAD")"    "$REPORT" "update-ref: report it"
msg "$WG" "$(bash_in "$W" "git branch -f main HEAD")"                "$REPORT" "branch -f: report it"
msg "$WG" "$(bash_in "$W" "git checkout -b other")"                  "$REPORT" "create a branch: report it"
msg "$WG" "$(bash_in "$W" "git pull origin other")"                  "run 'git merge main'" "pull: merge the base branch"
msg "$WG" "$(bash_in "$W" "git switch main")"                        "git show <commit>:<path>" \
  "move to another commit: read it with git show"
msg "$WG" "$(bash_in "$W" "git checkout --detach HEAD")"             "git show <commit>:<path>" \
  "detach: read it with git show"
PATH="$NOJQ" msg "$WG" "$(bash_in "$W" "git push")"                  "brew install jq" "without jq: install it"
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
# Found in the Q7 review: a scratch worktree shares the repo's refs, so `git -C <scratch>` must not skip the checks.
run "$WG" 0 "$(bash_in "$W" "git -C $SCR checkout $SHA")"                "a scratch worktree checks out a commit"
run "$WG" 2 "$(bash_in "$W" "git -C $SCR update-ref refs/heads/main HEAD")" "git -C <scratch worktree> update-ref"
run "$WG" 2 "$(bash_in "$W" "git -C $SCR push origin HEAD:main")"        "git -C <scratch worktree> push"
run "$WG" 2 "$(bash_in "$W" "git -C $SCR switch -c x")"                  "git -C <scratch worktree> switch -c"
run "$WG" 2 "$(bash_in "$W" "git -C $SCR merge story/C1-parser")"        "git -C <scratch worktree> merge a story"
run "$WG" 2 "$(bash_in "$W" "git -C $SCR checkout story/C1-parser")"     "git -C <scratch worktree> checks out a branch"
CLONE="$TMP/separate-clone"
git clone -q "$R" "$CLONE" 2>/dev/null
run "$WG" 0 "$(bash_in "$W" "git -C $CLONE update-ref refs/heads/main HEAD")" "git -C <separate clone> update-ref"
# Found in the Q7 re-review: a clone's origin is the shared repo, so its push moves shared branches.
msg "$WG" "$(bash_in "$W" "git -C $CLONE push origin HEAD:story/Q8-foo")" "$REPORT" \
  "git -C <separate clone> push: report it"
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
# Found in the Q7 security review (fixed in Q10): forms that got past the guard. Each blocked form names the way
# through; each has a legitimate near-miss that stays allowed.
echo "worker guard, Q7 review: stuck options, previous branch, worktree add, aliases, fetch refspecs"
SCR="$TMP/auditor-scratch-2"
git -C "$R" worktree add -q --detach "$SCR" 2>/dev/null
SCRATCH_ALT="git worktree add --detach <path> <commit>"
FETCH_ALT="Fetch without a destination"
ALIAS_ALT="Run the git command itself"
RESTORE_ALT="git checkout -- <path>"
READ_ALT="git show <commit>:<path>"
msg "$WG" "$(bash_in "$W" "git checkout -Bother")"                         "$REPORT" "checkout -B<name> (stuck)"
msg "$WG" "$(bash_in "$W" "git switch -cother")"                           "$REPORT" "switch -c<name> (stuck)"
msg "$WG" "$(bash_in "$W" "git switch -Cother")"                           "$REPORT" "switch -C<name> (stuck)"
msg "$WG" "$(bash_in "$W" "git checkout -qb other")"                       "$REPORT" "checkout -qb (bundled)"
msg "$WG" "$(bash_in "$W" "git checkout --orphan=other")"                  "$REPORT" "checkout --orphan=<name>"
msg "$WG" "$(bash_in "$W" "git -C $SCR checkout --track origin/other")"    "$REPORT" "scratch: checkout --track"
msg "$WG" "$(bash_in "$W" "git checkout -t origin/other")"                 "$REPORT" "checkout -t"
run "$WG" 0 "$(bash_in "$W" "git checkout -q -- src/app/models.py")"       "near-miss: checkout -q -- <path>"
msg "$WG" "$(bash_in "$W" "git -C $SCR checkout -")"                       "$READ_ALT" "scratch: checkout - (previous branch)"
msg "$WG" "$(bash_in "$W" "git -C $SCR checkout @{-1}")"                   "$READ_ALT" "scratch: checkout @{-1}"
run "$WG" 0 "$(bash_in "$W" "git -C $SCR checkout --detach HEAD")"         "near-miss: scratch detaches at HEAD"
msg "$WG" "$(bash_in "$W" "git switch -d")"                                "$READ_ALT" "switch -d (detach) in its own worktree"
msg "$WG" "$(bash_in "$W" "git checkout -m story/C1-parser")"              "$READ_ALT" "checkout -m <branch> (-m takes no value)"
msg "$WG" "$(bash_in "$W" 'git merge "story/C1-parser"')"                  "$REPORT" "merge a quoted branch"
msg "$WG" "$(bash_in "$W" "git checkout other-remote-branch")"             "$RESTORE_ALT" "checkout <name> git would guess"
rm "$W/eval/cases.json"
run "$WG" 0 "$(bash_in "$W" "git checkout eval/cases.json")"               "near-miss: checkout a deleted tracked file"
git -C "$W" checkout -q -- eval/cases.json
msg "$WG" "$(bash_in "$W" "git worktree add $TMP/wt-a story/C1-parser")"   "$SCRATCH_ALT" "worktree add on a branch"
msg "$WG" "$(bash_in "$W" "git worktree add -b x $TMP/wt-b")"              "$SCRATCH_ALT" "worktree add -b"
msg "$WG" "$(bash_in "$W" "git worktree add --detach --orphan $TMP/wt-c")" "$SCRATCH_ALT" "worktree add --orphan"
run "$WG" 0 "$(bash_in "$W" "git worktree add --no-checkout --detach \"$TMP/wt-d\" story/C1-parser")" \
  "near-miss: the test auditor's worktree add --no-checkout --detach"
run "$WG" 0 "$(bash_in "$W" "git worktree list")"                          "near-miss: worktree list"
SPACED="$TMP/sp ace clone"
git clone -q "$R" "$SPACED" 2>/dev/null
ESC=${SPACED// /\\ }
msg "$WG" "$(bash_in "$W" "git -C $ESC push origin HEAD:main")"            "$REPORT" "-C <path with escaped spaces> push"
run "$WG" 0 "$(bash_in "$W" "git -C $ESC update-ref refs/heads/main HEAD")" "near-miss: escaped-space clone update-ref"
msg "$WG" "$(bash_in "$W" "git --namespace foo push origin HEAD:main")"    "$REPORT" "--namespace <value> push"
REL=../../../../rel-clone                     # from the worktree $W, a clone at $TMP/rel-clone
git clone -q "$R" "$TMP/rel-clone" 2>/dev/null
msg "$WG" "$(bash_in "$W" "cd $R && git -C $REL merge story/C1-parser")"   "$REPORT" "cd, then a relative -C"
run "$WG" 0 "$(bash_in "$W" "git -C $REL merge story/C1-parser")"          "near-miss: relative -C on a clone, no cd"
msg "$WG" "$(bash_in "$W" "git fetch . HEAD:refs/heads/story/X9-x")"      "$FETCH_ALT" "fetch a refspec into a branch"
msg "$WG" "$(bash_in "$W" "git -C $R fetch $W HEAD:story/X9-x")"          "$FETCH_ALT" "-C <main> fetch a refspec"
run "$WG" 0 "$(bash_in "$W" "git fetch origin main")"                      "near-miss: fetch <remote> <branch>"
msg "$WG" "$(bash_in "$W" "git -c alias.x=push x origin HEAD")"            "$ALIAS_ALT" "-c alias.x=push"
msg "$WG" "$(bash_in "$W" "git x origin HEAD")"                            "$ALIAS_ALT" "an alias (unknown subcommand)"
msg "$WG" "$(bash_in "$W" "env A=1 git x")"                                "$ALIAS_ALT" "an alias after env"
run "$WG" 0 "$(bash_in "$W" "git -c core.pager=cat status")"               "near-miss: -c with another key"
run "$WG" 0 "$(bash_in "$W" "rg -n git src")"                              "near-miss: git as a search word"
run "$WG" 0 "$(bash_in "$W" "git merge --ff-only main")"                   "near-miss: the setup fast-forward to the base"
run "$WG" 0 "$(bash_in "$W" "python3 backlog.py tick --dry-run B4 done")"  "backlog.py tick --dry-run is allowed"
msg "$WG" "$(bash_in "$W" "python3 backlog.py show B4 --dry-run; python3 backlog.py tick B4 done")" "$FOLLOW" \
  "a dry run in another call doesn't cover a tick"
git -C "$R" worktree remove --force "$TMP/wt-d" 2>/dev/null
git -C "$R" worktree remove "$SCR" 2>/dev/null
echo "worker guard, Q10 review: branch renames, plumbing, wrappers, --git-dir, dry runs, paths and refs"
RENAME_ALT="git branch -m story/<ID>-<slug>"
MERGE_ALT="run 'git merge main'"
msg "$WG" "$(bash_in "$W" "git branch -m main oldmain")"                   "$RENAME_ALT" "branch -m <old> <new> renames another branch"
msg "$WG" "$(bash_in "$W" "git branch -m other")"                          "$RENAME_ALT" "branch -m to a non-story name"
msg "$WG" "$(bash_in "$W" "git branch -M story/C1-parser")"                "$RENAME_ALT" "branch -M can overwrite a branch"
msg "$WG" "$(bash_in "$W" "git branch -c story/C1-parser copy")"           "$REPORT" "branch -c copies a branch"
msg "$WG" "$(bash_in "$W" "git branch -qf other HEAD")"                    "$REPORT" "branch -qf (bundled force)"
run "$WG" 0 "$(bash_in "$W" "git branch -m story/B4-cases")"               "near-miss: the worker's own rename to its story name"
run "$WG" 0 "$(bash_in "$W" "git branch --list")"                          "near-miss: branch --list"
msg "$WG" "$(bash_in "$W" "git symbolic-ref HEAD refs/heads/main")"        "$REPORT" "symbolic-ref with a write"
msg "$WG" "$(bash_in "$W" "git send-pack $R main")"                        "$REPORT" "send-pack"
msg "$WG" "$(bash_in "$W" "git http-push https://example.invalid/r main")" "$REPORT" "http-push"
run "$WG" 0 "$(bash_in "$W" "git symbolic-ref HEAD")"                      "near-miss: symbolic-ref read"
msg "$WG" "$(bash_in "$W" "timeout 60 git p")"                             "$ALIAS_ALT" "an alias after timeout <secs>"
msg "$WG" "$(bash_in "$W" "stdbuf -o0 git p")"                             "$ALIAS_ALT" "an alias after stdbuf"
msg "$WG" "$(bash_in "$W" "nice -n 10 git p")"                             "$ALIAS_ALT" "an alias after nice -n <n>"
msg "$WG" "$(bash_in "$W" "true & git p")"                                 "$ALIAS_ALT" "an alias after a lone &"
msg "$WG" "$(bash_in "$W" "git config alias.p push")"                      "$ALIAS_ALT" "config writes an alias"
msg "$WG" "$(bash_in "$W" "git config --global --add alias.p push")"       "$ALIAS_ALT" "config --add writes an alias"
msg "$WG" "$(bash_in "$W" "git config set include.path $TMP/x")"           "$ALIAS_ALT" "config set include.path"
run "$WG" 0 "$(bash_in "$W" "git config --get alias.p")"                   "near-miss: config reads an alias"
run "$WG" 0 "$(bash_in "$W" "git config core.pager cat")"                  "near-miss: config sets another key"
run "$WG" 0 "$(bash_in "$W" "timeout 60 git status 2>&1")"                 "near-miss: timeout git status 2>&1"
msg "$WG" "$(bash_in "$W" "git -C $CLONE --git-dir=$R/.git update-ref refs/heads/main HEAD")" "$REPORT" \
  "clone -C with --git-dir on the shared repo"
msg "$WG" "$(bash_in "$W" "GIT_DIR=$R/.git git -C $CLONE branch -f main HEAD")" "$REPORT" "clone -C with GIT_DIR="
# Git reads a second -C relative to the first: here `rel` is the shared repo for git, a clone from the worker's cwd.
mkdir -p "$TMP/dd"; ln -s "$R" "$TMP/dd/rel"; ln -s "$TMP/rel-clone" "$W/rel"
msg "$WG" "$(bash_in "$W" "git -C $TMP/dd -C rel update-ref refs/heads/main HEAD")" "$REPORT" "two -C options"
run "$WG" 0 "$(bash_in "$W" "git -C rel update-ref refs/heads/main HEAD")" "near-miss: one -C on the clone"
rm "$W/rel"
msg "$WG" "$(bash_in "$W" "python3 backlog.py note B4 -- --dry-run")"     "$FOLLOW" "--dry-run after -- is note text"
msg "$WG" "$(bash_in "$W" "python3 backlog.py tick B4 done # --dry-run")" "$FOLLOW" "--dry-run in a comment"
msg "$WG" "$(bash_in "$W" "python3 backlog.py tick --dry-run B4 done > out.txt")" "$FOLLOW" "a dry run with a redirection"
git -C "$R" branch eval/cases.json 2>/dev/null                            # a branch named like a tracked file
msg "$WG" "$(bash_in "$W" "git checkout eval/cases.json")"                 "$READ_ALT" "a name that is a branch and a file"
run "$WG" 0 "$(bash_in "$W" "git checkout -- eval/cases.json")"            "near-miss: the same name after --"
git -C "$R" branch -D eval/cases.json >/dev/null 2>&1
run "$WG" 0 "$(bash_in "$W" 'git merge --message="x y" main')"            "near-miss: merge --message=<quoted> main"
msg "$WG" "$(bash_in "$W" 'git merge --message="x y" story/C1-parser')"   "$REPORT" "merge --message=<quoted> <story>"
echo x > "$W/sp file.txt"; git -C "$W" add "sp file.txt"; git -C "$W" commit -q -m "sp file"
run "$WG" 0 "$(bash_in "$W" 'git checkout sp\ file.txt')"                 "near-miss: checkout a tracked file with an escaped space"
msg "$WG" "$(bash_in "$W" 'git checkout no\ such')"                       "git checkout no such (" \
  "an escaped space prints as a space"
msg "$WG" "$(bash_in "$W" "git pull --rebase=true origin main")"           "$MERGE_ALT" "pull --rebase=true"
msg "$WG" "$(bash_in "$W" "git pull origin main other")"                   "$MERGE_ALT" "pull the base and another branch"
# Found in the 0.3.4 trial: the orchestrator's shell was still in a worktree after `cd <worktree> && uv run pytest`.
MERGE="git merge --no-ff story/B4-cases -m 'merge: story B4'"
run "$WG" 0 "$(jq -nc --arg c "cd $R && $MERGE" --arg d "$W" '{tool_name:"Bash",cwd:$d,tool_input:{command:$c}}')" \
  "the orchestrator merges from a shell left in a worktree"
run "$WG" 2 "$(bash_in "$W" "cd $R && $MERGE")"                           "a worker can't merge by cd-ing to the main checkout"

echo
[ "$FAILS" = 0 ] && echo "All guard tests passed." || { echo "$FAILS guard test(s) failed."; exit 1; }
