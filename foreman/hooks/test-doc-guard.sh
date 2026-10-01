#!/bin/bash
# Regression tests for the foreman doc guard hook (doc-guard.sh).
# Run: bash hooks/test-doc-guard.sh   (from the plugin root)
# Builds a throwaway repo (plus a second worktree) with its own config and markdown files; never touches your repo.

SRC="$(cd "$(dirname "$0")" && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
FAILS=0

R="$TMP/repo"
mkdir -p "$R/.claude/hooks/lib" "$R/docs/decisions" "$R/docs/other"
cp "$SRC/doc-guard.sh" "$R/.claude/hooks/"
cp "$SRC/lib/strip-heredocs.awk" "$R/.claude/hooks/lib/"

python3 -c "print(('x' * 200 + chr(10)) * 150, end='')" >"$R/docs/BIG.md"            # 150 lines, 30150 bytes
printf 'small file\n' >"$R/docs/SMALL.md"                                            # under the limit
python3 -c "print(('x' * 200 + chr(10)) * 150, end='')" >"$R/docs/decisions/001-x.md"  # excluded, also over
python3 -c "print(('y' * 200 + chr(10)) * 150, end='')" >"$R/docs/other/BIGGER.md"   # excluded by a glob
python3 -c "print(('z' * 5 + chr(10)) * 10000, end='')" >"$R/docs/HUGE.md"           # 10000 lines, 5 bytes each: a
                                                                                      # whole read-to-EOF from any
                                                                                      # offset would be way over the
                                                                                      # limit, but Read's own 2000-
                                                                                      # line default window is not.
printf 'plain text, not markdown\n' >"$R/NOTES.txt"
python3 -c "print(('x' * 200 + chr(10)) * 150, end='')" >"$R/docs/BIG.MARKDOWN"
python3 -c "print(('x' * 200 + chr(10)) * 150, end='')" >"$R/docs/big.mdx"
git -C "$R" init -q && git -C "$R" add -A && git -C "$R" commit -q -m init

run() {  # run <expected exit> <json> <label>
  printf '%s' "$2" | "$GUARD" >/dev/null 2>&1
  local c=$?
  if [ "$c" = "$1" ]; then echo "  ok    $3"; else echo "  FAIL  $3 (exit $c, want $1)"; FAILS=$((FAILS + 1)); fi
}
read_in() { jq -nc --arg d "$1" --arg p "$2" --argjson o "${3:-null}" --argjson l "${4:-null}" \
  '{tool_name:"Read",cwd:$d,tool_input:({file_path:$p} + (if $o == null then {} else {offset:$o} end) + (if $l == null then {} else {limit:$l} end))}'; }
bash_in() { jq -nc --arg c "$2" --arg d "$1" '{tool_name:"Bash",cwd:$d,tool_input:{command:$c}}'; }
read_str_limit() {  # read_in, but $3 is forced to be a JSON *string* (not a number) -- for the injection payload
  jq -nc --arg d "$1" --arg p "$2" --arg l "$3" '{tool_name:"Read",cwd:$d,tool_input:{file_path:$p, limit:$l}}'
}

GUARD="$R/.claude/hooks/doc-guard.sh"

echo "inactive: no 'docs' key in the config"
run 0 "$(read_in "$R" "$R/docs/BIG.md")"                        "no config at all: Read of the big file"

cat >"$R/.claude/foreman.json" <<'JSON'
{"docs": {"max_bytes": 20000, "exclude": ["docs/decisions", "docs/other/*.md"]}}
JSON
export CLAUDE_PROJECT_DIR="$R"

echo "active: 'docs' key present (max_bytes 20000)"
run 0 "$(read_in "$R" "$R/docs/SMALL.md")"                      "small .md allowed"
run 2 "$(read_in "$R" "$R/docs/BIG.md")"                        "large .md blocked whole"
run 0 "$(read_in "$R" "$R/docs/BIG.md" 1 50)"                   "range under the limit allowed"
run 2 "$(read_in "$R" "$R/docs/BIG.md" 1 15000)"                "range over the limit blocked"
run 0 "$(read_in "$R" "$R/docs/decisions/001-x.md")"            "excluded file (literal path) allowed, even though it's large"
run 0 "$(read_in "$R" "$R/docs/other/BIGGER.md")"               "excluded file (glob 'docs/other/*.md') allowed"
run 0 "$(read_in "$R/docs" "$R/docs/other/BIGGER.md")"          "same glob exclude allowed from a different cwd"
run 0 "$(read_in "$R" "$R/NOTES.txt")"                          "non-.md file allowed"
run 2 "$(read_in "$R" "$R/docs/BIG.MARKDOWN")"                  ".MARKDOWN (any case) blocked whole like .md"
run 2 "$(read_in "$R" "$R/docs/big.mdx")"                       ".mdx blocked whole like .md"

echo "offset/limit edge cases"
run 0 "$(read_in "$R" "docs/SMALL.md")"                         "relative Read path (small file) allowed"
run 2 "$(read_in "$R" "docs/BIG.md")"                           "relative Read path (big file) blocked"
run 0 "$(read_in "$R" "$R/docs/HUGE.md" 1 null)"                "offset-only: capped at Read's 2000-line default window (allowed)"
run 2 "$(read_in "$R" "$R/docs/HUGE.md")"                       "neither offset nor limit: the whole (over-limit) file blocked"
run 0 "$(read_in "$R" "$R/docs/HUGE.md" null 50)"               "limit-only (offset omitted): allowed"
run 0 "$(read_in "$R" "$R/docs/HUGE.md" 9500 null)"             "offset near EOF, no limit: allowed"

echo "limit/offset injection payload (security fix 1)"
MARK="$TMP/pwned-marker"
rm -f "$MARK"
PAYLOAD='1$(touch '"$MARK"')'
run 0 "$(read_str_limit "$R" "$R/docs/SMALL.md" "$PAYLOAD")"    "a non-digit limit payload is treated as absent, not evaluated"
if [ -e "$MARK" ]; then echo "  FAIL  the injection payload created a file"; FAILS=$((FAILS + 1))
else echo "  ok    the injection payload created no file"; fi

echo "Bash, best effort"
run 2 "$(bash_in "$R" "cat docs/BIG.md")"                       "Bash cat of the large file blocked"
run 0 "$(bash_in "$R" "sed -n '1,5p' docs/BIG.md")"             "Bash sed -n allowed"
run 0 "$(bash_in "$R" "rg -n foo docs/BIG.md")"                 "Bash rg allowed"
run 0 "$(bash_in "$R" "head -n 5 docs/BIG.md")"                 "Bash head -n allowed"
run 0 "$(bash_in "$R" "wc -l docs/BIG.md")"                     "Bash wc allowed"
run 0 "$(bash_in "$R" "git diff docs/BIG.md")"                  "Bash git diff allowed"
run 0 "$(bash_in "$R" "cat docs/SMALL.md")"                     "Bash cat of a small file allowed"
run 2 "$(bash_in "$R" "less docs/BIG.md")"                      "Bash less of the large file blocked"
run 2 "$(bash_in "$R" "command cat docs/BIG.md")"               "'command cat' blocked like cat"
run 2 "$(bash_in "$R" "xargs cat docs/BIG.md")"                 "'xargs cat' blocked like cat"
run 2 "$(bash_in "$R" "cd docs && cat BIG.md")"                 "a tracked preceding 'cd docs &&' still resolves the relative path"
run 0 "$(bash_in "$R" "cat docs/other/BIGGER.md")"              "Bash cat of a glob-excluded file allowed"

echo "redirects and pipes (security fix 7)"
run 0 "$(bash_in "$R" 'cat >> docs/BIG.md <<EOF
line
EOF')"                                                          "cat >> BIG.md <<EOF (append, a write) allowed"
run 0 "$(bash_in "$R" "cat > docs/BIG.md")"                     "cat > BIG.md (overwrite, a write) allowed"
run 0 "$(bash_in "$R" "cat < docs/BIG.md")"                     "cat < BIG.md (input redirect target skipped) allowed"
run 0 "$(bash_in "$R" "cat docs/BIG.md | grep x")"              "cat BIG.md | grep x (feeds a pipe) allowed"
run 2 "$(bash_in "$R" "cat docs/BIG.md 2>/dev/null")"           "cat BIG.md 2>/dev/null (still a real read) blocked"

echo "glob argument expansion (bypass hardening)"
run 2 "$(bash_in "$R" "cat docs/*.md")"                         "cat docs/*.md expands and catches the over-limit match"
run 0 "$(bash_in "$R" "cat docs/other/*.md")"                   "cat docs/other/*.md expands to only excluded matches"

echo "missing jq (simulated via PATH)"
NOJQ="$TMP/no-jq-bin"
mkdir -p "$NOJQ"
for tool in git sed awk wc tr cat dirname basename grep; do
  p=$(command -v "$tool" 2>/dev/null) && ln -sf "$p" "$NOJQ/$tool"
done
OUT=$(printf '%s' "$(read_in "$R" "$R/docs/SMALL.md")" | PATH="$NOJQ" "$GUARD" 2>&1)
RC=$?
if [ "$RC" = 2 ] && printf '%s' "$OUT" | grep -q "needs jq"; then echo "  ok    missing jq fails closed"
else echo "  FAIL  missing jq (exit $RC): $OUT"; FAILS=$((FAILS + 1)); fi

echo "cross-checkout exclude and size (security fix 6)"
W="$TMP/worktree2"
git -C "$R" worktree add -q "$W" -b wt2-branch >/dev/null 2>&1
run 0 "$(read_in "$R" "$W/docs/decisions/001-x.md")"            "excluded file via a worktree's path, cwd = main checkout"
run 0 "$(read_in "$W" "$R/docs/decisions/001-x.md")"            "excluded file via the main checkout's path, cwd = worktree"
run 2 "$(read_in "$W" "$R/docs/BIG.md")"                        "non-excluded big file still blocked via main checkout path, cwd = worktree"
run 2 "$(read_in "$R" "$W/docs/BIG.md")"                        "non-excluded big file still blocked via a worktree path, cwd = main checkout"
git -C "$R" worktree remove "$W" --force >/dev/null 2>&1

echo
[ "$FAILS" = 0 ] && echo "All doc guard tests passed." || { echo "$FAILS doc guard test(s) failed."; exit 1; }
