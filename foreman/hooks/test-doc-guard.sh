#!/bin/bash
# Regression tests for the foreman doc guard hook (doc-guard.sh). It guards the Read tool only.
# Run: bash hooks/test-doc-guard.sh   (from the plugin root)
# Builds a throwaway repo (plus a second worktree) with its own config and markdown files; never touches your repo.

SRC="$(cd "$(dirname "$0")" && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
FAILS=0

R="$TMP/repo"
mkdir -p "$R/.claude/hooks" "$R/docs/decisions" "$R/docs/other" "$R/CaseTest"
cp "$SRC/doc-guard.sh" "$R/.claude/hooks/"

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
python3 -c "print(('x' * 200 + chr(10)) * 150, end='')" >"$R/CaseTest/BIG.md"        # for the case-exact test
git -C "$R" init -q && git -C "$R" add -A && git -C "$R" commit -q -m init

run() {  # run <expected exit> <json> <label>
  printf '%s' "$2" | "$GUARD" >/dev/null 2>&1
  local c=$?
  if [ "$c" = "$1" ]; then echo "  ok    $3"; else echo "  FAIL  $3 (exit $c, want $1)"; FAILS=$((FAILS + 1)); fi
}
read_in() { jq -nc --arg d "$1" --arg p "$2" --argjson o "${3:-null}" --argjson l "${4:-null}" \
  '{tool_name:"Read",cwd:$d,tool_input:({file_path:$p} + (if $o == null then {} else {offset:$o} end) + (if $l == null then {} else {limit:$l} end))}'; }
read_str_limit() {  # read_in, but $3 is forced to be a JSON *string* (not a number) -- for the injection payload
  jq -nc --arg d "$1" --arg p "$2" --arg l "$3" '{tool_name:"Read",cwd:$d,tool_input:{file_path:$p, limit:$l}}'
}

GUARD="$R/.claude/hooks/doc-guard.sh"

echo "inactive: no 'docs' key in the config"
run 0 "$(read_in "$R" "$R/docs/BIG.md")"                        "no config at all: Read of the big file"

cat >"$R/.claude/foreman.json" <<'JSON'
{"docs": {"max_bytes": 20000, "exclude": ["docs/decisions", "docs/other/*.md", "casetest/big.md"]}}
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
run 2 "$(read_in "$R" "$R/CaseTest/BIG.md")"                    "exclude is case-exact: 'casetest/big.md' doesn't exempt 'CaseTest/BIG.md'"

echo "offset/limit edge cases"
run 0 "$(read_in "$R" "docs/SMALL.md")"                         "relative path (small file) allowed"
run 2 "$(read_in "$R" "docs/BIG.md")"                           "relative path (big file) blocked"
run 0 "$(read_in "$R" "$R/docs/HUGE.md" 1 null)"                "offset-only: capped at Read's 2000-line default window (allowed)"
run 2 "$(read_in "$R" "$R/docs/HUGE.md")"                       "neither offset nor limit: the whole (over-limit) file blocked"
run 0 "$(read_in "$R" "$R/docs/HUGE.md" null 50)"               "limit-only (offset omitted): allowed"
run 0 "$(read_in "$R" "$R/docs/HUGE.md" 9500 null)"             "offset near EOF, no limit: allowed"

echo "limit/offset injection payload"
MARK="$TMP/pwned-marker"
rm -f "$MARK"
PAYLOAD='1$(touch '"$MARK"')'
run 0 "$(read_str_limit "$R" "$R/docs/SMALL.md" "$PAYLOAD")"    "a non-digit limit payload is treated as absent, not evaluated"
if [ -e "$MARK" ]; then echo "  FAIL  the injection payload created a file"; FAILS=$((FAILS + 1))
else echo "  ok    the injection payload created no file"; fi

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

echo "cross-checkout exclude and size, a sibling worktree"
W="$TMP/worktree2"
git -C "$R" worktree add -q "$W" -b wt2-branch >/dev/null 2>&1
run 0 "$(read_in "$R" "$W/docs/decisions/001-x.md")"            "excluded file via a worktree's path, cwd = main checkout"
run 0 "$(read_in "$W" "$R/docs/decisions/001-x.md")"            "excluded file via the main checkout's path, cwd = worktree"
run 2 "$(read_in "$W" "$R/docs/BIG.md")"                        "non-excluded big file still blocked via main checkout path, cwd = worktree"
run 2 "$(read_in "$R" "$W/docs/BIG.md")"                        "non-excluded big file still blocked via a worktree path, cwd = main checkout"
git -C "$R" worktree remove "$W" --force >/dev/null 2>&1

echo "Bash is not looked at any more"
run 0 "$(jq -nc --arg d "$R" '{tool_name:"Bash",cwd:$d,tool_input:{command:"cat docs/BIG.md"}}')" \
  "a Bash cat of the large file is not blocked: this guard only looks at Read"

echo "cross-checkout exclude, a worktree nested under the main checkout"
NW="$R/.claude/worktrees/w1"
git -C "$R" worktree add -q "$NW" -b nested-wt-branch >/dev/null 2>&1
run 0 "$(read_in "$R" "$NW/docs/decisions/001-x.md")"           "excluded file in a nested worktree via its own path, cwd = main checkout"
run 0 "$(read_in "$NW" "$R/docs/decisions/001-x.md")"           "excluded file via the main checkout's path, cwd = nested worktree"
run 2 "$(read_in "$NW" "$NW/docs/BIG.md")"                      "non-excluded big file in the nested worktree, cwd = the nested worktree"
run 2 "$(read_in "$R" "$NW/docs/BIG.md")"                       "non-excluded big file in the nested worktree, cwd = main checkout"
git -C "$R" worktree remove "$NW" --force >/dev/null 2>&1

echo
[ "$FAILS" = 0 ] && echo "All doc guard tests passed." || { echo "$FAILS doc guard test(s) failed."; exit 1; }
