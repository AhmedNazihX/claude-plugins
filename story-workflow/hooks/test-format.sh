#!/bin/bash
# Tests for format.sh. Run: bash hooks/test-format.sh (from the plugin root). Builds a throwaway repo.

HOOK="$(cd "$(dirname "$0")" && pwd)/format.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
FAILS=0
R="$TMP/repo with space"
mkdir -p "$R/.claude" "$R/backend/app" "$R/docs"
# The "formatter" upper-cases the file, and records the folder it ran in, so the test can check both.
cat > "$R/.claude/story-workflow.json" <<'JSON'
{"format": {"backend/": "tr a-z A-Z < {file} > {file}.tmp && mv {file}.tmp {file} && pwd > ../ran-in"}}
JSON
echo "hello" > "$R/backend/app/x.py"
echo "hello" > "$R/docs/notes.md"
git -C "$R" init -q
export CLAUDE_PROJECT_DIR="$R"

check() {  # check <label> <condition>
  if eval "$2"; then echo "  ok    $1"; else echo "  FAIL  $1"; FAILS=$((FAILS + 1)); fi
}
edit() { jq -nc --arg f "$1" --arg d "$R" '{tool_name:"Edit",cwd:$d,tool_input:{file_path:$f}}' | "$HOOK"; }

edit "$R/backend/app/x.py"
check "a file under a prefix is formatted" '[ "$(cat "$R/backend/app/x.py")" = "HELLO" ]'
check "the formatter runs from the prefix folder" '[ "$(cat "$R/ran-in")" = "$(cd "$R/backend" && pwd -P)" ]'
edit "$R/docs/notes.md"
check "a file outside every prefix is left alone" '[ "$(cat "$R/docs/notes.md")" = "hello" ]'
echo '{"format": {"backend/": "echo broken >&2; exit 3"}}' > "$R/.claude/story-workflow.json"
OUT=$(edit "$R/backend/app/x.py" 2>/dev/null); CODE=$?
check "a failing formatter doesn't block (exit 0)" '[ $CODE = 0 ]'
check "the failure reaches Claude as additional context" 'echo "$OUT" | jq -e ".hookSpecificOutput.additionalContext | test(\"broken\")" >/dev/null'

# A file in a story worktree is formatted there, with the main checkout's config (not the worktree's copy).
cat > "$R/.claude/story-workflow.json" <<'JSON'
{"format": {"backend/": "tr a-z A-Z < {file} > {file}.tmp && mv {file}.tmp {file}"}}
JSON
git -C "$R" add -A && git -C "$R" -c user.email=t@t -c user.name=t commit -q -m init
WT="$TMP/wt"
git -C "$R" worktree add -q -b story/X1-y "$WT"
echo '{"format": {"backend/": "echo pwned > ../pwned"}}' > "$WT/.claude/story-workflow.json"
echo "hello" > "$WT/backend/app/x.py"
edit "$WT/backend/app/x.py"
check "a worktree file is formatted in the worktree" '[ "$(cat "$WT/backend/app/x.py")" = "HELLO" ]'
check "the worktree's own config copy is not used" '[ ! -e "$WT/pwned" ]'
rm "$R/.claude/story-workflow.json"
echo "hello" > "$R/backend/app/x.py"
edit "$R/backend/app/x.py"
check "no config, no formatting" '[ "$(cat "$R/backend/app/x.py")" = "hello" ]'

echo
if [ "$FAILS" = 0 ]; then echo "All format tests passed."; else echo "$FAILS format test(s) failed."; exit 1; fi
