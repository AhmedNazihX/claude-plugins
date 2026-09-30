#!/bin/bash
# Regression tests for the git and secrets guards. Run: bash tests/test-guards.sh (from the plugin root).
# Fake keys are built at runtime, so no key-shaped string sits in this file.

H="$(cd "$(dirname "$0")/../hooks" && pwd)"
GIT="$H/block-dangerous-git.sh"
SEC="$H/block-secrets.sh"
FAILS=0

run() {  # run <hook> <expected exit> <json> <label>
  printf '%s' "$3" | "$1" >/dev/null 2>&1
  local c=$?
  if [ "$c" = "$2" ]; then echo "  ok    $4"; else echo "  FAIL  $4 (exit $c, want $2)"; FAILS=$((FAILS + 1)); fi
}
asks() {  # asks <json> <label>: the hook answers with a permission prompt
  if printf '%s' "$1" | "$GIT" 2>/dev/null | grep -q '"permissionDecision": *"ask"'; then echo "  ok    $2"
  else echo "  FAIL  $2 (no ask)"; FAILS=$((FAILS + 1)); fi
}
bash_cmd() { jq -nc --arg c "$1" '{tool_name:"Bash",tool_input:{command:$c}}'; }
tool_path() { jq -nc --arg t "$1" --arg p "$2" '{tool_name:$t,tool_input:{file_path:$p}}'; }
write_content() { jq -nc --arg p "$1" --arg c "$2" '{tool_name:"Write",tool_input:{file_path:$p,content:$c}}'; }

echo "git guard"
run "$GIT" 2 "$(bash_cmd 'git push --force origin main')" "force push is blocked"
run "$GIT" 2 "$(bash_cmd 'git push origin +main')" "+refspec push is blocked"
run "$GIT" 2 "$(bash_cmd 'git reset --hard HEAD~1')" "reset --hard is blocked"
run "$GIT" 2 "$(bash_cmd 'git clean -fd')" "clean -fd is blocked"
run "$GIT" 2 "$(bash_cmd 'git branch -D story/C1-x')" "branch -D is blocked"
run "$GIT" 2 "$(bash_cmd 'git checkout .')" "checkout . is blocked"
asks "$(bash_cmd 'git push origin main')" "a normal push asks"
run "$GIT" 0 "$(bash_cmd 'git status')" "git status passes"
run "$GIT" 0 "$(bash_cmd 'git branch -d story/C1-x')" "branch -d (safe delete) passes"
# Bypasses found in the 2026-09-30 review: spacing, flag order, combined flags, global options.
run "$GIT" 2 "$(bash_cmd 'git clean -df')" "clean -df is blocked"
run "$GIT" 2 "$(bash_cmd 'git clean -dfx')" "clean -dfx is blocked"
run "$GIT" 2 "$(bash_cmd 'git -C /x clean -xdf')" "clean after -C is blocked"
run "$GIT" 2 "$(bash_cmd 'git reset  --hard')" "reset with two spaces is blocked"
run "$GIT" 2 "$(bash_cmd 'cd x && git   reset --hard HEAD')" "reset after && is blocked"
run "$GIT" 2 "$(bash_cmd 'git checkout -f')" "checkout -f is blocked"
run "$GIT" 2 "$(bash_cmd 'git checkout HEAD -- .')" "checkout HEAD -- . is blocked"
run "$GIT" 2 "$(bash_cmd 'git restore -- .')" "restore -- . is blocked"
run "$GIT" 2 "$(bash_cmd 'git switch --discard-changes main')" "switch --discard-changes is blocked"
run "$GIT" 2 "$(bash_cmd 'git stash drop')" "stash drop is blocked"
run "$GIT" 2 "$(bash_cmd 'git branch --delete --force x')" "branch --delete --force is blocked"
run "$GIT" 2 "$(bash_cmd 'git worktree remove --force /tmp/x')" "worktree remove --force is blocked"
run "$GIT" 2 "$(bash_cmd 'git push -fu origin x')" "combined -fu push is blocked"
asks "$(bash_cmd 'git -c user.name=x push origin main')" "push after -c asks"
asks "$(bash_cmd 'git --no-pager push')" "push after --no-pager asks"
run "$GIT" 0 "$(bash_cmd 'git clean -n')" "clean -n (dry run) passes"
run "$GIT" 0 "$(bash_cmd 'git checkout -b feature')" "checkout -b passes"
run "$GIT" 0 "$(bash_cmd 'git worktree remove /tmp/x')" "worktree remove without --force passes"
run "$GIT" 0 "$(bash_cmd 'git stash push -m wip')" "stash push passes"
run "$GIT" 0 "$(bash_cmd 'git merge --no-ff story/C1-x -m "merge: story C1"')" "a merge passes"
run "$GIT" 0 "$(printf '%s' '{"tool_input":{"command":"git commit -F- <<EOF\ndocs: never git push --force\nEOF"}}')" "a heredoc commit message that mentions a force push passes"

echo "secrets guard"
run "$SEC" 2 "$(tool_path Read /x/.env)" "reading .env is blocked"
run "$SEC" 2 "$(tool_path Read /x/deploy.key)" "reading a .key file is blocked"
run "$SEC" 0 "$(tool_path Read /x/.env.example)" "reading .env.example passes"
run "$SEC" 2 "$(bash_cmd 'cat .env')" "cat .env is blocked"
run "$SEC" 0 "$(bash_cmd 'ln -s /main/.env .env')" "linking .env into a worktree passes"
KEY="sk-or-v1-$(printf 'a%.0s' {1..40})"
run "$SEC" 2 "$(write_content /x/a.py "k='$KEY'")" "writing a real-looking key is blocked"
run "$SEC" 0 "$(write_content /x/a.py "k='sk-or-v1-xxx'")" "a short placeholder passes"
grep_tool() { jq -nc --arg p "$1" --arg g "$2" '{tool_name:"Grep",tool_input:{pattern:"x",path:$p,glob:$g}}'; }
run "$SEC" 2 "$(grep_tool /x/.env '')" "Grep on .env is blocked"
run "$SEC" 2 "$(grep_tool /x '.env*')" "Grep with an .env glob is blocked"
run "$SEC" 0 "$(grep_tool /x '*.py')" "Grep over code passes"
run "$SEC" 2 "$(bash_cmd 'grep -rn API_KEY .')" "recursive grep without an exclude is blocked"
run "$SEC" 0 "$(bash_cmd "grep -rn --exclude='.env*' API_KEY .")" "recursive grep excluding .env passes"
run "$SEC" 0 "$(bash_cmd 'grep -n API_KEY settings.py')" "a plain grep in one file passes"
run "$SEC" 0 "$(bash_cmd 'grep -rn x . --include=*.md')" "recursive grep limited by --include passes"
run "$SEC" 2 "$(bash_cmd "grep -rn x . --include='.env*'")" "recursive grep including .env is blocked"
run "$SEC" 0 "$(bash_cmd 'rg API_KEY')" "rg (skips hidden files) passes"
run "$SEC" 2 "$(bash_cmd 'rg --hidden API_KEY')" "rg --hidden is blocked"
run "$SEC" 2 "$(bash_cmd 'env | grep KEY')" "env | grep is blocked"
run "$SEC" 2 "$(bash_cmd 'printenv')" "printenv is blocked"
run "$SEC" 2 "$(bash_cmd 'printenv OPENROUTER_API_KEY')" "printenv of a key is blocked"
run "$SEC" 0 "$(bash_cmd 'printenv PATH')" "printenv PATH passes"
run "$SEC" 0 "$(bash_cmd 'env FOO=1 python3 -c pass')" "env running a command passes"
run "$SEC" 2 "$(bash_cmd 'export -p')" "export -p is blocked"
run "$SEC" 0 "$(printf '%s' '{"tool_name":"Bash","tool_input":{"command":"cat > notes.md <<EOF\nnever cat .env\nEOF"}}')" "a heredoc body that mentions cat .env passes"
# The false positive of 2026-09-30: jq's .key field is not a key file.
run "$SEC" 0 "$(bash_cmd "jq -r 'to_entries[] | \"\\(.key) \\(.value)\"' config.json && sed -n 1p README.md")" "jq .key with sed passes"

echo
if [ "$FAILS" = 0 ]; then echo "All guard tests passed."; else echo "$FAILS guard test(s) failed."; exit 1; fi
